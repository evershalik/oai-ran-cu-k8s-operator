# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import PropertyMock, call, patch

import pytest
from charms.oai_ran_cu_k8s.v0.fiveg_f1 import FivegF1Error
from ops import BoundEvent, testing

from tests.unit.lib.charms.oai_ran_cu_k8s.v0.test_charms.test_provider_charm.src.charm import (
    WhateverCharm,
)

TEST_CHARM_PATH = "tests.unit.lib.charms.oai_ran_cu_k8s.v0.test_charms.test_provider_charm.src.charm.WhateverCharm"  # noqa: E501
FIVEG_F1_PROVIDER_EVENTS_PATH = "charms.oai_ran_cu_k8s.v0.fiveg_f1.FivegF1ProviderCharmEvents"
RELATION_NAME = "fiveg_f1"


class TestFivegF1Provides:
    patcher_f1_ip_address = patch(
        f"{TEST_CHARM_PATH}.TEST_F1_IP_ADDRESS", new_callable=PropertyMock
    )
    patcher_f1_port = patch(f"{TEST_CHARM_PATH}.TEST_F1_PORT", new_callable=PropertyMock)
    patcher_fiveg_f1_requirer_available = patch(
        f"{FIVEG_F1_PROVIDER_EVENTS_PATH}.fiveg_f1_requirer_available"
    )

    @pytest.fixture()
    def setUp(self) -> None:
        self.mock_f1_ip_address = TestFivegF1Provides.patcher_f1_ip_address.start()
        self.mock_f1_port = TestFivegF1Provides.patcher_f1_port.start()
        self.mock_fiveg_f1_requirer_available = (
            TestFivegF1Provides.patcher_fiveg_f1_requirer_available.start()
        )
        self.mock_fiveg_f1_requirer_available.__class__ = BoundEvent

    def tearDown(self) -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def setup_harness(self, setUp, request):
        self.harness = testing.Harness(WhateverCharm)
        self.harness.begin()
        self.harness.set_leader(is_leader=True)
        yield self.harness
        self.harness.cleanup()
        request.addfinalizer(self.tearDown)

    def test_given_valid_f1_interface_data_when_fiveg_f1_relation_joined_then_f1_ip_address_and_port_are_pushed_to_the_relation_databag(  # noqa: E501
        self,
    ):
        test_f1_ip_address = "123.123.123.123"
        test_f1_port = 1234
        self.mock_f1_ip_address.return_value = test_f1_ip_address
        self.mock_f1_port.return_value = test_f1_port

        relation_id = self.harness.add_relation(
            relation_name=RELATION_NAME, remote_app="whatever-app"
        )
        self.harness.add_relation_unit(relation_id, "whatever-app/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app
        )

        assert test_f1_ip_address == relation_data["f1_ip_address"]
        assert str(test_f1_port) == relation_data["f1_port"]

    def test_given_invalid_f1_ip_address_when_fiveg_f1_relation_joined_then_error_is_raised(self):
        test_f1_ip_address = "555.555.555.555"
        test_f1_port = 1234
        self.mock_f1_ip_address.return_value = test_f1_ip_address
        self.mock_f1_port.return_value = test_f1_port

        with pytest.raises(FivegF1Error):
            relation_id = self.harness.add_relation(
                relation_name=RELATION_NAME, remote_app="whatever-app"
            )
            self.harness.add_relation_unit(relation_id, "whatever-app/0")

    def test_given_invalid_f1_port_when_fiveg_f1_relation_joined_then_error_is_raised(self):
        test_f1_ip_address = "123.123.123.123"
        test_f1_port = "that's wrong"
        self.mock_f1_ip_address.return_value = test_f1_ip_address
        self.mock_f1_port.return_value = test_f1_port

        with pytest.raises(FivegF1Error):
            relation_id = self.harness.add_relation(
                relation_name=RELATION_NAME, remote_app="whatever-app"
            )
            self.harness.add_relation_unit(relation_id, "whatever-app/0")

    def test_given_fiveg_f1_relation_created_when_relation_changed_then_event_with_requirer_f1_port_is_emitted(  # noqa: E501
        self,
    ):
        test_f1_ip_address = "123.123.123.123"
        test_f1_port = 1234
        test_requirer_f1_port = 4321
        self.mock_f1_ip_address.return_value = test_f1_ip_address
        self.mock_f1_port.return_value = test_f1_port

        relation_id = self.harness.add_relation(
            relation_name=RELATION_NAME, remote_app="whatever-app"
        )
        self.harness.add_relation_unit(relation_id, "whatever-app/0")
        self.harness.update_relation_data(
            relation_id=relation_id,
            app_or_unit="whatever-app",
            key_values={"f1_port": str(test_requirer_f1_port)},
        )

        calls = [
            call.emit(f1_port=str(test_requirer_f1_port)),
        ]
        self.mock_fiveg_f1_requirer_available.assert_has_calls(calls)
