import os


ROOT_FOLDER_NAME = "PitLane FM"
CONFIG_FILE_NAME = "Pit_Lane_FM_Config.ini"


def _program_files_root() -> str:
    return (
        os.environ.get("ProgramW6432")
        or os.environ.get("ProgramFiles")
        or r"C:\Program Files"
    )


def _appdata_root() -> str:
    return os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"),
        "AppData",
        "Roaming",
    )


def install_root() -> str:
    return os.path.join(_program_files_root(), ROOT_FOLDER_NAME)


def app_install_dir(app_name: str) -> str:
    return os.path.join(install_root(), app_name)


def shared_radio_dir() -> str:
    return os.path.join(install_root(), "Radio")


def app_config_dir(app_name: str) -> str:
    return os.path.join(_appdata_root(), ROOT_FOLDER_NAME, app_name)


def app_config_file(app_name: str) -> str:
    return os.path.join(app_config_dir(app_name), CONFIG_FILE_NAME)


def default_music_source_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Music")
