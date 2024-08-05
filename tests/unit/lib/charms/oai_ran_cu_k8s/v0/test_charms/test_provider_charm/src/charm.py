# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from charms.oai_ran_cu_k8s.v0.fiveg_f1 import F1Provides
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus

logger = logging.getLogger(__name__)


class WhateverCharm(CharmBase):
    TEST_F1_IP_ADDRESS = ""
    TEST_F1_PORT = int()

    def __init__(self, *args):
        """Create a new instance of this object for each event."""
        super().__init__(*args)
        self.fiveg_f1_provider = F1Provides(self, "fiveg_f1")

        self.framework.observe(
            self.fiveg_f1_provider.on.fiveg_f1_request, self._on_fiveg_f1_request
        )
        self.framework.observe(
            self.fiveg_f1_provider.on.fiveg_f1_requirer_available,
            self._on_fiveg_f1_requirer_available,
        )

    def _on_fiveg_f1_request(self, _):
        self.fiveg_f1_provider.set_f1_information(
            f1_ip_address=self.TEST_F1_IP_ADDRESS, f1_port=self.TEST_F1_PORT
        )

    def _on_fiveg_f1_requirer_available(self, _):
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(WhateverCharm)
