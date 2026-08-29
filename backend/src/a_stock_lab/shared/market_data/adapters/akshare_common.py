from importlib.metadata import PackageNotFoundError, version

AKSHARE_PROVIDER_ID = "akshare"


def installed_akshare_version() -> str:
    try:
        return version("akshare")
    except PackageNotFoundError:
        return "unknown"
