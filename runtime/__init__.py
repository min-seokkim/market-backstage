"""Runtime orchestration — prepare() + signal injection.

The simulation core is in `core/`; this package handles workflow:
- `prepare()`: ingest → calibrate → build → connect → push signals → propagate
- `signals`: DB observations → actor inbox signal/shock injection
"""
