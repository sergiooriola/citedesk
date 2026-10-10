from importlib.metadata import version

import citedesk


def test_the_package_reports_the_installed_version() -> None:
    assert citedesk.__version__ == version("citedesk")
