# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from charms.oai_ran_cu_k8s.v0.fiveg_f1 import F1Requires
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus

logger = logging.getLogger(__name__)


class WhateverCharm(CharmBase):
    TEST_F1_PORT = int()

    def __init__(self, *args):
        """Create a new instance of this object for each event."""
        super().__init__(*args)
        self.fiveg_f1_requirer = F1Requires(self, "fiveg_f1")

        self.framework.observe(
            self.fiveg_f1_requirer.on.fiveg_f1_provider_available,
            self._on_fiveg_f1_provider_available,
        )

    def _on_fiveg_f1_provider_available(self, _):
        self.fiveg_f1_requirer.set_f1_information(f1_port=self.TEST_F1_PORT)
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(WhateverCharm)
