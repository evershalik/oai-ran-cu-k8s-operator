#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import call, patch

import pytest
from charm import OAIRANCUOperator
from lightkube.models.apps_v1 import StatefulSetSpec
from lightkube.models.core_v1 import (
    Container,
    PodSpec,
    PodTemplateSpec,
    SecurityContext,
)
from lightkube.models.meta_v1 import LabelSelector
from lightkube.resources.apps_v1 import StatefulSet
from ops import testing
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

MULTUS_LIB = "charms.kubernetes_charm_libraries.v0.multus.KubernetesMultusCharmLib"
GNB_IDENTITY_LIB = "charms.sdcore_gnbsim_k8s.v0.fiveg_gnb_identity.GnbIdentityProvides"
MULTUS_K8S_CLIENT = "charms.kubernetes_charm_libraries.v0.multus.KubernetesClient"
F1_LIB = "charms.oai_ran_cu_k8s.v0.fiveg_f1.F1Provides"
NAMESPACE = "whatever"
WORKLOAD_CONTAINER_NAME = "cu"


class TestCharm:
    patcher_lightkube_client = patch("lightkube.core.client.GenericSyncClient")
    patcher_lightkube_client_get = patch("lightkube.core.client.Client.get")
    patcher_lightkube_client_replace = patch("lightkube.core.client.Client.replace")
    patcher_k8s_service_patch = patch("charm.KubernetesServicePatch")
    patcher_multus_ready = patch(f"{MULTUS_LIB}.is_ready")
    patcher_multus_available = patch(f"{MULTUS_LIB}.multus_is_available")
    patcher_gnb_identity = patch(f"{GNB_IDENTITY_LIB}.publish_gnb_identity_information")
    patcher_f1_set_information = patch(f"{F1_LIB}.set_f1_information")
    patcher_check_output = patch("charm.check_output")
    patcher_multus_statefulset_patch = patch(f"{MULTUS_K8S_CLIENT}.statefulset_is_patched")

    @pytest.fixture()
    def setUp(self):
        self.mock_lightkube_client = TestCharm.patcher_lightkube_client.start()
        self.mock_lightkube_client_get = TestCharm.patcher_lightkube_client_get.start()
        self.mock_lightkube_client_replace = TestCharm.patcher_lightkube_client_replace.start()
        self.mock_k8s_service_patch = TestCharm.patcher_k8s_service_patch.start()
        self.mock_multus_ready = TestCharm.patcher_multus_ready.start()
        self.mock_multus_available = TestCharm.patcher_multus_available.start()
        self.mock_gnb_identity = TestCharm.patcher_gnb_identity.start()
        self.mock_check_output = TestCharm.patcher_check_output.start()
        self.mock_multus_statefulset_patch = TestCharm.patcher_multus_statefulset_patch.start()
        self.mock_f1_set_information = TestCharm.patcher_f1_set_information.start()

    def tearDown(self) -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def setup_harness(self, setUp, request):
        self.mock_multus_ready.return_value = True
        self.mock_multus_available.return_value = True
        self.harness = testing.Harness(OAIRANCUOperator)
        self.harness.set_model_name(name=NAMESPACE)
        self.harness.set_leader(is_leader=True)
        self.harness.set_can_connect(container=WORKLOAD_CONTAINER_NAME, val=True)
        self.harness.begin()
        yield self.harness
        self.harness.cleanup()
        request.addfinalizer(self.tearDown)

    def test_given_unit_is_not_leader_when_config_changed_then_status_is_blocked(self):
        self.harness.set_leader(is_leader=False)

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == BlockedStatus(
            "Scaling is not implemented for this charm"
        )

    @pytest.mark.parametrize(
        "config_param,value",
        [
            pytest.param("n3-ip-address", "", id="empty_n3_ip-address"),
            pytest.param("n3-ip-address", "4.5", id="invalid_n3_ip-address"),
            pytest.param("f1-ip-address", "", id="empty_f1_ip-address"),
            pytest.param("f1-ip-address", "5.5.5/3", id="invalid_f1_ip-address"),
            pytest.param("f1-port", int(), id="empty_f1_port"),
            pytest.param("n2-interface-name", "", id="empty_n2_interface_name"),
            pytest.param("n3-interface-name", "", id="empty_n3_interface_name"),
            pytest.param("f1-interface-name", "", id="empty_f1_interface_name"),
            pytest.param("n2-ip-address", "", id="empty_n2_ip_address"),
            pytest.param("n2-ip-address", "3/3", id="invalid_n2_ip_address"),
            pytest.param("mcc", "", id="empty_mcc"),
            pytest.param("mnc", "", id="empty_mnc"),
            pytest.param("sst", int(), id="empty_sst"),
            pytest.param("tac", int(), id="empty_tac"),
        ],
    )
    def test_given_invalid_config_when_config_changed_then_status_is_blocked(
        self, config_param, value
    ):
        self.harness.update_config(key_values={config_param: value})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == BlockedStatus(
            f"The following configurations are not valid: ['{config_param}']"
        )

    def test_given_macvlan_cni_type_when_network_attachment_definitions_from_config_is_called_then_interfaces_type_are_macvlan(  # noqa: E501
        self,
    ):
        self.harness.disable_hooks()
        self.harness.update_config(
            key_values={
                "cni-type": "macvlan",
                "n3-interface-name": "ran",
                "f1-interface-name": "du",
                "n2-interface-name": "core",
            }
        )
        self.harness.evaluate_status()
        nad = self.harness.charm._network_attachment_definitions_from_config()
        config_n3 = json.loads(nad[0].spec["config"])  # type: ignore
        assert config_n3["type"] == "macvlan"
        assert config_n3["master"] == "ran"
        config_f1 = json.loads(nad[1].spec["config"])  # type: ignore
        assert config_f1["type"] == "macvlan"
        assert config_f1["master"] == "du"
        config_n2 = json.loads(nad[2].spec["config"])  # type: ignore
        assert config_n2["type"] == "macvlan"
        assert config_n2["master"] == "core"

    def test_given_default_config_when_network_attachment_definitions_from_config_is_called_then_interfaces_types_are_bridge(  # noqa: E501
        self,
    ):
        self.harness.disable_hooks()
        self.harness.update_config(key_values={})
        self.harness.evaluate_status()
        nad = self.harness.charm._network_attachment_definitions_from_config()
        assert nad[0].spec
        config_n3 = json.loads(nad[0].spec["config"])
        assert config_n3["type"] == "bridge"
        config_f1 = json.loads(nad[0].spec["config"])
        assert config_f1["type"] == "bridge"
        config_n2 = json.loads(nad[0].spec["config"])
        assert config_n2["type"] == "bridge"

    def test_given_upf_subnet_and_n3_gw_provided_when_network_attachment_definitions_from_config_is_called_then_route_is_created(  # noqa: E501
        self,
    ):
        self.harness.disable_hooks()
        self.harness.update_config(
            key_values={
                "n3-gateway-ip": "192.168.1.12",
                "upf-subnet": "172.10.0.0/24",
            }
        )
        self.harness.evaluate_status()
        nad = self.harness.charm._network_attachment_definitions_from_config()
        assert nad[0].spec
        config_n3 = json.loads(nad[0].spec["config"])
        assert config_n3["routes"] == [
            {
                "dst": "172.10.0.0/24",
                "gw": "192.168.1.12",
            },
        ]

    def test_given_n2_relation_not_created_when_config_changed_then_status_is_blocked(self):
        self.harness.set_leader(is_leader=True)

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == BlockedStatus(
            "Waiting for N2 relation to be created"
        )

    def test_given_workload_container_cant_be_connected_to_when_config_changed_then_status_is_waiting(  # noqa: E501
        self,
    ):
        self.create_n2_relation()
        self.harness.set_can_connect(container=WORKLOAD_CONTAINER_NAME, val=False)

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus("Waiting for container to be ready")

    def test_given_pod_ip_is_not_available_when_config_changed_then_status_is_waiting(  # noqa: E501
        self,
    ):
        self.mock_check_output.return_value = b""
        self.create_n2_relation()

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus(
            "Waiting for Pod IP address to be available"
        )

    def test_given_charm_statefulset_is_not_patched_when_config_changed_then_status_is_waiting(
        self,
    ):
        test_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=False),
                            )
                        ]
                    )
                ),
            )
        )
        self.mock_lightkube_client_get.return_value = test_statefulset
        self.mock_check_output.return_value = b"1.1.1.1"
        self.create_n2_relation()

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus(
            "Waiting for statefulset to be patched"
        )

    def test_give_storage_is_not_attached_when_config_changed_then_status_is_waiting(self):
        test_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=True),
                            )
                        ]
                    )
                ),
            )
        )
        self.mock_lightkube_client_get.return_value = test_statefulset
        self.mock_check_output.return_value = b"1.1.1.1"
        self.create_n2_relation()

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus(
            "Waiting for storage to be attached"
        )

    def test_given_amf_n2_information_is_not_available_when_config_changed_then_status_is_waiting(
        self,
    ):
        test_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=True),
                            )
                        ]
                    )
                ),
            )
        )
        self.mock_lightkube_client_get.return_value = test_statefulset
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage("config", attach=True)
        self.create_n2_relation()

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus("Waiting for N2 information")

    def test_given_all_status_check_are_ok_when_config_changed_then_status_is_active(self):
        test_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=True),
                            )
                        ]
                    )
                ),
            )
        )
        self.mock_lightkube_client_get.return_value = test_statefulset
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage("config", attach=True)
        self.set_n2_relation_data()

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == ActiveStatus()

    def test_given_statefulset_is_not_patched_when_config_changed_then_statefulset_is_patched(
        self,
    ):
        test_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=False),
                            )
                        ]
                    )
                ),
            )
        )
        expected_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=True),
                            )
                        ]
                    )
                ),
            )
        )
        self.mock_lightkube_client_get.return_value = test_statefulset
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage("config", attach=True)
        self.set_n2_relation_data()

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        self.mock_lightkube_client_replace.assert_called_once_with(obj=expected_statefulset)

    def test_given_statefulset_is_patched_when_config_changed_then_statefulset_is_not_patched(
        self,
    ):
        self.prepare_workload_for_configuration()

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        self.mock_lightkube_client_replace.assert_not_called()

    def test_given_multus_disabled_when_collect_status_then_status_is_blocked(self):
        self.prepare_workload_for_configuration()
        self.mock_multus_available.return_value = False
        self.harness.evaluate_status()

        assert self.harness.model.unit.status == BlockedStatus(
            "Multus is not installed or enabled"
        )

    def test_given_multus_not_configured_when_collect_status_then_status_is_waiting(
        self,
    ):
        self.prepare_workload_for_configuration()
        self.mock_multus_ready.return_value = False
        self.harness.evaluate_status()

        assert self.harness.model.unit.status == WaitingStatus("Waiting for Multus to be ready")

    def test_given_workload_is_ready_to_be_configured_when_config_changed_then_cu_config_file_is_generated_and_pushed_to_the_workload_container(  # noqa: E501
        self,
    ):
        root = self.harness.get_filesystem_root(WORKLOAD_CONTAINER_NAME)
        self.prepare_workload_for_configuration()

        self.harness.update_config(key_values={})
        with open("tests/unit/resources/expected_config.conf") as expected_config_file:
            expected_config = expected_config_file.read()
        assert (root / "tmp/conf/cu.conf").read_text() == expected_config.strip()

    def test_given_cu_config_file_is_up_to_date_when_config_changed_then_cu_config_file_is_not_pushed_to_the_workload_container(  # noqa: E501
        self,
    ):
        self.prepare_workload_for_configuration()
        root = self.harness.get_filesystem_root(WORKLOAD_CONTAINER_NAME)
        (root / "tmp/conf/cu.conf").write_text(
            self._read_file("tests/unit/resources/expected_config.conf").strip()
        )
        config_modification_time = (root / "tmp/conf/cu.conf").stat().st_mtime

        self.harness.update_config(key_values={})

        assert (root / "tmp/conf/cu.conf").stat().st_mtime == config_modification_time

    def test_given_charm_configuration_is_done_when_config_changed_then_pebble_layer_is_created(
        self,
    ):
        expected_pebble_plan = {
            "services": {
                "cu": {
                    "override": "replace",
                    "startup": "enabled",
                    "command": "/opt/oai-gnb/bin/nr-softmodem -O /tmp/conf/cu.conf --sa",
                    "environment": {
                        "OAI_GDBSTACKS": "1",
                        "TZ": "UTC",
                    },
                },
            },
        }
        self.prepare_workload_for_configuration()
        root = self.harness.get_filesystem_root(WORKLOAD_CONTAINER_NAME)
        (root / "tmp/conf/cu.conf").write_text(
            self._read_file("tests/unit/resources/expected_config.conf").strip()
        )

        self.harness.update_config(key_values={})

        updated_plan = self.harness.get_container_pebble_plan(WORKLOAD_CONTAINER_NAME).to_dict()
        assert expected_pebble_plan == updated_plan

    def test_given_charm_is_configured_and_running_when_fiveg_gnb_identity_relation_is_added_then_default_tac_is_published(  # noqa: E501
        self,
    ):
        self.prepare_workload_for_configuration()
        root = self.harness.get_filesystem_root(WORKLOAD_CONTAINER_NAME)
        (root / "tmp/conf/cu.conf").write_text(
            self._read_file("tests/unit/resources/expected_config.conf").strip()
        )

        relation_id = self.harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
        self.harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")

        self.mock_gnb_identity.assert_called_once_with(
            relation_id=relation_id,
            gnb_name=f"{NAMESPACE}-{self.harness.charm.app.name}-cu",
            tac=1,
        )

    def test_given_charm_is_configured_and_running_when_f1_relation_is_added_then_f1_interface_ip_and_port_is_published(  # noqa: E501
        self,
    ):
        self.prepare_workload_for_configuration()
        root = self.harness.get_filesystem_root(WORKLOAD_CONTAINER_NAME)
        (root / "tmp/conf/cu.conf").write_text(
            self._read_file("tests/unit/resources/expected_config.conf").strip()
        )
        self.harness.evaluate_status()
        f1_relation_id = self.harness.add_relation(relation_name="fiveg_f1", remote_app="du")
        self.harness.add_relation_unit(relation_id=f1_relation_id, remote_unit_name="du/0")

        self.mock_f1_set_information.assert_called_once_with(
            ip_address="192.168.251.7",
            port=2153,
        )

    def test_given_default_config_when_network_attachment_definitions_from_config_is_called_then_nads_created_for_the_provided_interfaces(  # noqa: E501
        self,
    ):
        self.harness.disable_hooks()
        self.harness.update_config(
            key_values={
                "n3-interface-name": "dummy-n3",
                "f1-interface-name": "dummy-f1",
                "n2-interface-name": "dummy-n2",
            }
        )
        self.harness.evaluate_status()
        nad = self.harness.charm._network_attachment_definitions_from_config()
        assert nad[0].metadata.name == "dummy-n3-net"  # type: ignore
        assert nad[1].metadata.name == "dummy-f1-net"  # type: ignore
        assert nad[2].metadata.name == "dummy-n2-net"  # type: ignore

    def test_given_charm_is_active_when_config_changed_then_updated_f1_interface_ip_and_port_is_published(  # noqa: E501
        self,
    ):
        test_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=True),
                            )
                        ]
                    )
                ),
            )
        )
        self.mock_lightkube_client_get.return_value = test_statefulset
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage("config", attach=True)
        self.set_n2_relation_data()
        f1_relation_id = self.harness.add_relation(relation_name="fiveg_f1", remote_app="du")
        self.harness.add_relation_unit(relation_id=f1_relation_id, remote_unit_name="du/0")
        self.harness.update_config(key_values={"f1-ip-address": "10.3.5.1/24", "f1-port": 3522})
        self.harness.evaluate_status()
        self.mock_f1_set_information.assert_has_calls(
            [
                call(ip_address="192.168.251.7", port=2153),
                call(ip_address="10.3.5.1", port=3522),
            ]
        )

    def create_n2_relation(self) -> int:
        """Create a relation between the CU and the AMF.

        Returns:
            int: ID of the created relation
        """
        amf_relation_id = self.harness.add_relation(relation_name="fiveg_n2", remote_app="amf")
        self.harness.add_relation_unit(relation_id=amf_relation_id, remote_unit_name="amf/0")
        return amf_relation_id

    def set_n2_relation_data(self) -> int:
        """Create the N2 relation, set the relation data in the n2 relation and return its ID.

        Returns:
            int: ID of the created relation
        """
        amf_relation_id = self.create_n2_relation()
        self.harness.update_relation_data(
            relation_id=amf_relation_id,
            app_or_unit="amf",
            key_values={
                "amf_hostname": "amf",
                "amf_port": "38412",
                "amf_ip_address": "1.2.3.4",
            },
        )
        return amf_relation_id

    def prepare_workload_for_configuration(self):
        test_statefulset = StatefulSet(
            spec=StatefulSetSpec(
                selector=LabelSelector(),
                serviceName="whatever",
                template=PodTemplateSpec(
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=WORKLOAD_CONTAINER_NAME,
                                securityContext=SecurityContext(privileged=True),
                            )
                        ]
                    )
                ),
            )
        )
        self.mock_lightkube_client_get.return_value = test_statefulset
        self.mock_check_output.return_value = b"1.1.1.1"
        self.harness.add_storage("config", attach=True)
        self.set_n2_relation_data()

    @staticmethod
    def _read_file(path: str) -> str:
        """Read a file and returns as a string.

        Args:
            path (str): path to the file.

        Returns:
            str: content of the file.
        """
        with open(path, "r") as f:
            content = f.read()
        return content
