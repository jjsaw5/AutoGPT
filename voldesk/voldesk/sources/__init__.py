"""Optional market-data source integrations for Vol Desk.

Everything under ``voldesk.sources`` is additive: the core rule engine
(``voldesk.grading``, ``voldesk.exits``, ``voldesk.regime``, ...) still
works purely from vendor CSV exports and never imports from this
subpackage. Modules here exist to help populate the well-defined GEX/DEX/
VEX/CEX math in ``voldesk.gex`` from a live options-chain data provider,
as an alternative to a manual CSV export -- they cannot supply the Vol
Desk proprietary levels (pTrans, nTrans, COTMP, COTMC, grade, db_change)
since no published formula exists for those.
"""

from __future__ import annotations
