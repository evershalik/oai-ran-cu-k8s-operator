# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import PropertyMock, call, patch

import pytest
from ops import BoundEvent, testing
from test_charms.test_requirer_charm.src.charm import WhateverCharm  # type: ignore[import]

TEST_CHARM_PATH = "test_charms.test_requirer_charm.src.charm.WhateverCharm"
FIVEG_F1_REQUIRER_EVENTS_PATH = (
    "charms.oai_ran_cu_k8s.v0.fiveg_f1.FivegF1RequirerCharmEvents"
)
FIVEG_F1_REQUIRES_PATH = (
    "charms.oai_ran_cu_k8s.v0.fiveg_f1.F1Requires"
)
RELATION_NAME = "fiveg_f1"


class TestFivegF1Requires:
    patcher_f1_port = patch(f"{TEST_CHARM_PATH}.TEST_F1_PORT", new_callable=PropertyMock)
    patcher_fiveg_f1_provider_available = patch(
        f"{FIVEG_F1_REQUIRER_EVENTS_PATH}.fiveg_f1_provider_available"
    )

    @pytest.fixture()
    def setUp(self) -> None:
        self.mock_f1_port = TestFivegF1Requires.patcher_f1_port.start()

    def tearDown(self) -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def harness(self, setUp, request):
        self.harness = testing.Harness(WhateverCharm)
        self.harness.begin()
        self.harness.set_leader(is_leader=True)
        yield self.harness
        self.harness.cleanup()
        request.addfinalizer(self.tearDown)

    def test_given_fiveg_f1_relation_created_when_relation_changed_then_event_with_provider_f1_ip_address_and_port_is_emitted(  # noqa: E501
        self,
    ):
        mock_fiveg_f1_provider_available = (
            TestFivegF1Requires.patcher_fiveg_f1_provider_available.start()
        )
        mock_fiveg_f1_provider_available.__class__ = BoundEvent
        test_f1_port = 1234
        test_provider_f1_ip_address = "123.123.123.123"
        test_provider_f1_port = 4321
        self.mock_f1_port.return_value = test_f1_port

        relation_id = self.harness.add_relation(
            relation_name=RELATION_NAME, remote_app="whatever-app"
        )
        self.harness.add_relation_unit(relation_id, "whatever-app/0")
        self.harness.update_relation_data(
            relation_id=relation_id,
            app_or_unit="whatever-app",
            key_values={
                "f1_ip_address": test_provider_f1_ip_address,
                "f1_port": str(test_provider_f1_port),
            },
        )

        calls = [
            call.emit(
                f1_ip_address=test_provider_f1_ip_address,
                f1_port=str(test_provider_f1_port),
            ),
        ]
        mock_fiveg_f1_provider_available.assert_has_calls(calls)

    def test_given_valid_f1_port_when_fiveg_f1_provider_available_then_requirer_f1_port_is_pushed_to_the_relation_databag(  # noqa: E501
        self,
    ):
        test_f1_port = 1234
        test_provider_f1_ip_address = "123.123.123.123"
        test_provider_f1_port = 4321
        self.mock_f1_port.return_value = test_f1_port

        relation_id = self.harness.add_relation(
            relation_name=RELATION_NAME, remote_app="whatever-app"
        )
        self.harness.add_relation_unit(relation_id, "whatever-app/0")
        self.harness.update_relation_data(
            relation_id=relation_id,
            app_or_unit="whatever-app",
            key_values={
                "f1_ip_address": test_provider_f1_ip_address,
                "f1_port": str(test_provider_f1_port),
            },
        )

        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app
        )

        assert str(test_f1_port) == relation_data["f1_port"]

    def test_given_invalid_f1_port_when_fiveg_f1_provider_available_then_value_error_is_raised(
        self,
    ):
        test_f1_port = "Not a valid port"
        test_provider_f1_ip_address = "123.123.123.123"
        test_provider_f1_port = 4321
        self.mock_f1_port.return_value = test_f1_port

        with pytest.raises(ValueError):
            relation_id = self.harness.add_relation(
                relation_name=RELATION_NAME, remote_app="whatever-app"
            )
            self.harness.add_relation_unit(relation_id, "whatever-app/0")
            self.harness.update_relation_data(
                relation_id=relation_id,
                app_or_unit="whatever-app",
                key_values={
                    "f1_ip_address": test_provider_f1_ip_address,
                    "f1_port": str(test_provider_f1_port),
                },
            )
