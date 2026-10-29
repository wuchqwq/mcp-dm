# Independent DM provider — coding contract

Read `DM_QUALIFICATION_CONTRACT.md`, an unchanged snapshot of the source project's
AGENTS.md, before altering any bridge/native code. Its scientific guards,
ABI/build/dtype eligibility, source protection, request recovery, lifecycle,
historical FAIL/NOT_TESTED records and no-hardware-control rules still apply.
Do not rebuild, load or qualify anything merely to complete repository migration.

This package owns only DM operations. Historical instructions about combined
image/structure/UI modules do not grant them ownership here: they now belong to
the independent Microscopy Core. Do not import or require that repository.
Keep the legacy `dm_*` public tool contracts and both explicit host backends.
Never silently substitute external scientific processing for a failed DM call.

Keep Python host integration compatible with its original GMS environment.
Run targeted tests; real host and scientific qualification are distinct from
mock/protocol smoke. Do not merge, publish or modify a user's running DM instance
without explicit authorization.
