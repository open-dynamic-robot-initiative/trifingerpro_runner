from setuptools import setup

PACKAGE_NAME = "trifingerpro_runner"

setup(
    name=PACKAGE_NAME,
    version="1.0.0",
    # Packages to export
    packages=[PACKAGE_NAME],
    # This is important as well
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Felix Widmaier",
    maintainer_email="felix.widmaier@tue.mpg.de",
    description="Scripts for executing jobs on the TriFingerPro robots.",
    license="BSD 3-clause",
    entry_points={
        "console_scripts": [
            "run_submission = trifingerpro_runner.run_submission:main",
        ],
    },
)
