# Behavior references

These frozen Python implementations are test oracles for the C migration.
They are never staged into OpenWrt and are not runtime alternatives.
Production C tests are in `devices/t551m/test_screen_runtime.py` and
`devices/t551m/test_screen_native.py`; legacy protocol/browser tests use these
references to preserve the earlier contracts. Change production C and its tests
when fixing runtime behavior, rather than updating this reference in parallel.
