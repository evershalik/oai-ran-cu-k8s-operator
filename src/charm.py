#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed operator for the OAI RAN Central Unit (CU) for K8s."""

import logging
from ipaddress import IPv4Address
from subprocess import check_output
from typing import Optional

from charm_config import CharmConfig, CharmConfigInvalidError
from charms.oai_ran_cu_k8s.v0.fiveg_f1 import F1Provides
from charms.observability_libs.v1.kubernetes_service_patch import (
    KubernetesServicePatch,
)
from charms.sdcore_amf_k8s.v0.fiveg_n2 import N2Requires
from charms.sdcore_gnbsim_k8s.v0.fiveg_gnb_identity import (
    GnbIdentityProvides,
)
from jinja2 import Environment, FileSystemLoader
from k8s_privileged import K8sPrivileged
from lightkube.models.core_v1 import ServicePort
from ops import ActiveStatus, BlockedStatus, CollectStatusEvent, WaitingStatus
from ops.charm import CharmBase
from ops.main import main
from ops.pebble import Layer

logger = logging.getLogger(__name__)

BASE_CONFIG_PATH = "/tmp/conf"
CONFIG_FILE_NAME = "cu.conf"
F1_RELATION_NAME = "fiveg_f1"
N2_RELATION_NAME = "fiveg_n2"
GNB_IDENTITY_RELATION_NAME = "fiveg_gnb_identity"
DU_F1_DEFAULT_PORT = 2153
WORKLOAD_VERSION_FILE_NAME = "/etc/workload-version"


class OAIRANCUOperator(CharmBase):
    """Main class to describe Juju event handling for the OAI RAN CU operator for K8s."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)
        if not self.unit.is_leader():
            return
        self._container_name = self._service_name = "cu"
        self._container = self.unit.get_container(self._container_name)
        self._n2_requirer = N2Requires(self, N2_RELATION_NAME)
        self._gnb_identity_provider = GnbIdentityProvides(self, GNB_IDENTITY_RELATION_NAME)
        self._f1_provider = F1Provides(self, F1_RELATION_NAME)
        self._k8s_privileged = K8sPrivileged(
            namespace=self.model.name, statefulset_name=self.app.name
        )
        try:
            self._charm_config: CharmConfig = CharmConfig.from_charm(charm=self)
        except CharmConfigInvalidError:
            return
        self._service_patcher = KubernetesServicePatch(
            charm=self,
            ports=[
                ServicePort(name="f1", port=self._charm_config.f1_port, protocol="UDP"),
                ServicePort(name="n2", port=36412, protocol="SCTP"),
                ServicePort(name="n3", port=2152, protocol="UDP"),
            ],
        )

        self.framework.observe(self.on.update_status, self._configure)
        self.framework.observe(self.on.config_changed, self._configure)
        self.framework.observe(self.on.cu_pebble_ready, self._configure)
        self.framework.observe(self.on.fiveg_n2_relation_joined, self._configure)
        self.framework.observe(self._n2_requirer.on.n2_information_available, self._configure)
        self.framework.observe(self._f1_provider.on.fiveg_f1_request, self._configure)
        self.framework.observe(self._f1_provider.on.fiveg_f1_requirer_available, self._configure)
        self.framework.observe(
            self._gnb_identity_provider.on.fiveg_gnb_identity_request,
            self._configure,
        )

    def _on_collect_unit_status(self, event: CollectStatusEvent):
        """Check the unit status and set to Unit when CollectStatusEvent is fired.

        Set the workload version if present in workload
        Args:
            event: CollectStatusEvent
        """
        if not self.unit.is_leader():
            # NOTE: In cases where leader status is lost before the charm is
            # finished processing all teardown events, this prevents teardown
            # event code from running. Luckily, for this charm, none of the
            # teardown code is necessary to perform if we're removing the
            # charm.
            event.add_status(BlockedStatus("Scaling is not implemented for this charm"))
            logger.info("Scaling is not implemented for this charm")
            return
        try:
            self._charm_config: CharmConfig = CharmConfig.from_charm(charm=self)
        except CharmConfigInvalidError as exc:
            event.add_status(BlockedStatus(exc.msg))
            return
        if not self._relation_created(N2_RELATION_NAME):
            event.add_status(BlockedStatus("Waiting for N2 relation to be created"))
            logger.info("Waiting for N2 relation to be created")
            return
        if not self._container.can_connect():
            event.add_status(WaitingStatus("Waiting for container to be ready"))
            logger.info("Waiting for container to be ready")
            return
        if not _get_pod_ip():
            event.add_status(WaitingStatus("Waiting for Pod IP address to be available"))
            logger.info("Waiting for Pod IP address to be available")
            return
        if not self._k8s_privileged.is_patched(container_name=self._container_name):
            event.add_status(WaitingStatus("Waiting for statefulset to be patched"))
            logger.info("Waiting for statefulset to be patched")
            return
        self.unit.set_workload_version(self._get_workload_version())
        if not self._container.exists(path=BASE_CONFIG_PATH):
            event.add_status(WaitingStatus("Waiting for storage to be attached"))
            logger.info("Waiting for storage to be attached")
            return
        if not self._n2_requirer.amf_hostname:
            event.add_status(WaitingStatus("Waiting for N2 information"))
            logger.info("Waiting for N2 information")
            return
        event.add_status(ActiveStatus())

    def _configure(self, _) -> None:
        try:
            self._charm_config: CharmConfig = CharmConfig.from_charm(charm=self)
        except CharmConfigInvalidError:
            return
        if not self._relation_created(N2_RELATION_NAME):
            return
        if not self._container.can_connect():
            return
        if not self._container.exists(path=BASE_CONFIG_PATH):
            return
        if not _get_pod_ip():
            return
        if not self._n2_requirer.amf_hostname:
            return

        if not self._k8s_privileged.is_patched(container_name=self._container_name):
            self._k8s_privileged.patch_statefulset(container_name=self._container_name)
        cu_config = self._generate_cu_config()
        if config_update_required := not self._is_cu_config_up_to_date(cu_config):
            self._write_config_file(content=cu_config)
        service_restart_required = config_update_required
        self._configure_pebble(restart=service_restart_required)

        self._update_fiveg_f1_relation_data()
        self._update_fiveg_gnb_identity_relation_data()

    def _relation_created(self, relation_name: str) -> bool:
        """Return whether a given Juju relation was created.

        Args:
            relation_name (str): Relation name

        Returns:
            bool: Whether the relation was created.
        """
        return bool(self.model.relations.get(relation_name))

    def _generate_cu_config(self) -> str:
        if self._f1_provider.requirer_f1_port:
            du_f1_port = self._f1_provider.requirer_f1_port
        else:
            logger.info(
                "DU F1 port information not available. Using default value %s", DU_F1_DEFAULT_PORT
            )
            du_f1_port = DU_F1_DEFAULT_PORT
        if not (pod_ip := _get_pod_ip()):
            logger.warning("Pod IP address not available")
            return ""
        if not self._n2_requirer.amf_ip_address:
            logger.warning("AMF IP address not available")
            return ""
        return _render_config_file(
            gnb_name=self._gnb_name,
            cu_f1_interface_name=self._charm_config.f1_interface_name,
            cu_f1_ip_address=pod_ip,
            cu_f1_port=self._charm_config.f1_port,
            du_f1_port=du_f1_port,
            cu_n2_interface_name=self._charm_config.n2_interface_name,
            cu_n2_ip_address=pod_ip,
            cu_n3_interface_name=self._charm_config.n3_interface_name,
            cu_n3_ip_address=pod_ip,
            amf_external_address=self._n2_requirer.amf_ip_address,
            mcc=self._charm_config.mcc,
            mnc=self._charm_config.mnc,
            sst=self._charm_config.sst,
            tac=self._charm_config.tac,
        )

    def _is_cu_config_up_to_date(self, content: str) -> bool:
        """Check whether the CU config file content matches the actual charm configuration.

        Args:
            content (str): desired config file content

        Returns:
            True if config is up-to-date else False
        """
        return self._config_file_is_written() and self._config_file_content_matches(
            content=content
        )

    def _config_file_is_written(self) -> bool:
        return bool(self._container.exists(f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}"))

    def _config_file_content_matches(self, content: str) -> bool:
        if not self._container.exists(path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}"):
            return False
        existing_content = self._container.pull(path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}")
        return existing_content.read() == content

    def _write_config_file(self, content: str) -> None:
        self._container.push(source=content, path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}")
        logger.info("Config file written")

    def _configure_pebble(self, restart=False) -> None:
        """Configure the Pebble layer.

        Args:
            restart (bool): Whether to restart the CU container.
        """
        plan = self._container.get_plan()
        if plan.services != self._cu_pebble_layer.services:
            self._container.add_layer(self._container_name, self._cu_pebble_layer, combine=True)
            self._container.replan()
            logger.info("New layer added: %s", self._cu_pebble_layer)
        if restart:
            self._container.restart(self._service_name)
            logger.info("Restarted container %s", self._service_name)
            return

    def _update_fiveg_gnb_identity_relation_data(self) -> None:
        """Publish GNB name and TAC in the `fiveg_gnb_identity` relation data bag."""
        if not self.unit.is_leader():
            return
        fiveg_gnb_identity_relations = self.model.relations.get(GNB_IDENTITY_RELATION_NAME)
        if not fiveg_gnb_identity_relations:
            logger.info("No %s relations found.", GNB_IDENTITY_RELATION_NAME)
            return

        tac = self._charm_config.tac
        if not tac:
            logger.error(
                "TAC value cannot be published on the %s relation", GNB_IDENTITY_RELATION_NAME
            )
            return
        for gnb_identity_relation in fiveg_gnb_identity_relations:
            self._gnb_identity_provider.publish_gnb_identity_information(
                relation_id=gnb_identity_relation.id, gnb_name=self._gnb_name, tac=tac
            )

    def _update_fiveg_f1_relation_data(self) -> None:
        """Publish F1 interface information in the `fiveg_f1` relation data bag."""
        if not self.unit.is_leader():
            return
        fiveg_f1_relations = self.model.relations.get(F1_RELATION_NAME)
        if not fiveg_f1_relations:
            logger.info("No %s relations found.", F1_RELATION_NAME)
            return
        if not (pod_ip := _get_pod_ip()):
            logger.error("Pod IP address not available")
            return
        self._f1_provider.set_f1_information(ip_address=pod_ip, port=self._charm_config.f1_port)

    @property
    def _gnb_name(self) -> str:
        """The gNB's name contains the model name and the app name.

        Returns:
            str: the gNB's name.
        """
        return f"{self.model.name}-{self.app.name}-cu"

    @property
    def _cu_pebble_layer(self) -> Layer:
        """Return pebble layer for the cu container.

        Returns:
            Layer: Pebble Layer
        """
        return Layer(
            {
                "services": {
                    self._service_name: {
                        "override": "replace",
                        "startup": "enabled",
                        "command": f"/opt/oai-gnb/bin/nr-softmodem -O {BASE_CONFIG_PATH}/{CONFIG_FILE_NAME} --sa",  # noqa: E501
                        "environment": self._cu_environment_variables,
                    },
                },
            }
        )

    @property
    def _cu_environment_variables(self) -> dict:
        return {
            "OAI_GDBSTACKS": "1",
            "TZ": "UTC",
        }

    def _get_workload_version(self) -> str:
        """Return the workload version.

        Checks for the presence of /etc/workload-version file
        and if present, returns the contents of that file. If
        the file is not present, an empty string is returned.

        Returns:
            string: A human-readable string representing the version of the workload
        """
        if self._container.exists(path=WORKLOAD_VERSION_FILE_NAME):
            version_file_content = self._container.pull(path=WORKLOAD_VERSION_FILE_NAME).read()
            return version_file_content
        return ""


def _render_config_file(
    *,
    gnb_name: str,
    cu_f1_interface_name: str,
    cu_f1_ip_address: str,
    cu_f1_port: int,
    du_f1_port: int,
    cu_n2_interface_name: str,
    cu_n2_ip_address: str,
    cu_n3_interface_name: str,
    cu_n3_ip_address: str,
    amf_external_address: str,
    mcc: str,
    mnc: str,
    sst: int,
    tac: int,
) -> str:
    """Render CU config file based on parameters.

    Args:
        gnb_name: The name of the gNodeB
        cu_f1_interface_name: Name of the network interface used for F1 traffic
        cu_f1_ip_address: IPv4 address of the network interface used for F1 traffic
        cu_f1_port: Number of the port used by the CU for F1 traffic
        du_f1_port: Number of the port used by the DU for F1 traffic
        cu_n2_interface_name: Name of the network interface used for N2 traffic
        cu_n2_ip_address: IPv4 address of the network interface used for N2 traffic
        cu_n3_interface_name: Name of the network interface used for N3 traffic
        cu_n3_ip_address: IPv4 address of the network interface used for N3 traffic
        amf_external_address: AMF hostname
        mcc: Mobile Country Code
        mnc: Mobile Network Code
        sst: Slice Selection Type
        tac: Tracking Area Code

    Returns:
        str: Rendered CU configuration file
    """
    jinja2_env = Environment(loader=FileSystemLoader("src/templates"))
    template = jinja2_env.get_template("cu.conf.j2")
    return template.render(
        gnb_name=gnb_name,
        cu_f1_interface_name=cu_f1_interface_name,
        cu_f1_ip_address=cu_f1_ip_address,
        cu_f1_port=cu_f1_port,
        du_f1_port=du_f1_port,
        cu_n2_interface_name=cu_n2_interface_name,
        cu_n2_ip_address=cu_n2_ip_address,
        cu_n3_interface_name=cu_n3_interface_name,
        cu_n3_ip_address=cu_n3_ip_address,
        amf_external_address=amf_external_address,
        mcc=mcc,
        mnc=mnc,
        sst=sst,
        tac=tac,
    )


def _get_pod_ip() -> Optional[str]:
    """Return the pod IP using juju client.

    Returns:
        str: The pod IP.
    """
    ip_address = check_output(["unit-get", "private-address"])
    return str(IPv4Address(ip_address.decode().strip())) if ip_address else None


if __name__ == "__main__":  # pragma: nocover
    main(OAIRANCUOperator)
