import setuptools
import discoger._info as package_info

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name=package_info.__title__,  # How you named your package folder (MyLib)
    packages=setuptools.find_packages(),
    version=package_info.__version__,  # Start with a small number and increase it with every
    license=package_info.__license__,
    description=package_info.__description__,  # Give a short description about your library
    long_description=long_description,
    long_description_content_type="text/markdown",
    author=package_info.__author__,  # Type in your name
    author_email=package_info.__author_email__,  # Type in your E-Mail
    url=f"https://github.com/{package_info.__github_username__}/{package_info.__title__}",  #
    download_url=f"https://github.com/{package_info.__github_username__}/{package_info.__title__}/archive/{package_info.__version__}.tar.gz",
    keywords=package_info.__keywords__,
    entry_points={"console_scripts": ["discoger = discoger.client:main"]},
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Development Status :: 5 - Production/Stable",
        # Chose either "3 - Alpha", "4 - Beta" or "5 - Production/Stable" as the current state
        "Programming Language :: Python :: 3",  # Specify which python versions that you want
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Internet :: WWW/HTTP",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
)
