from .cli import main


def entrypoint():
    """Make captured CLI output UTF-8 independently of the host console locale."""
    import sys
    for stream in (sys.stdout, sys.stderr):
        configure = getattr(stream, "reconfigure", None)
        if configure is not None:
            configure(encoding="utf-8", errors="strict")
    return main()


if __name__ == "__main__":
    raise SystemExit(entrypoint())
