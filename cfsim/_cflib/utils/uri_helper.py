import os


def uri_from_env(env='CFLIB_URI', default='radio://0/80/2M/E7E7E7E7E7') -> str:
    try:
        return os.environ[env]
    except KeyError:
        return default


def address_from_env(env='CFLIB_URI', default=0xE7E7E7E7E7) -> int:
    try:
        uri = os.environ[env]
    except KeyError:
        return default
    return int(uri.rstrip('/').split('/')[-1], 16)
