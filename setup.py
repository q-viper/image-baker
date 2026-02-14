import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="imagebaker",
    use_scm_version=True,
    setup_requires=["setuptools_scm"],
    author="Ramkrishna Acharya",
    author_email="qramkrishna@gmail.com",
    description="A package for baking images.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/q-viper/Image-Baker",
    license="MIT",
    packages=setuptools.find_packages(exclude=["docs", "docs.*", "site", "site.*", "assets", "assets.*", "examples", "examples.*", "tests", "tests.*", "experiments", "experiments.*"]),
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        "numpy>=1.24.0",
        "opencv-python>=4.8.0",
        "pillow>=10.0.0",
        "pydantic>=2.11.1",
        "typer>=0.9.0",
        "PySide6==6.8.3",
        "loguru",
    ],
    entry_points={
        "console_scripts": [
            "imagebaker=imagebaker.cli:app",
        ],
    },
    extras_require={
        "docs": [
            "mkdocs>=1.4",
            "mkdocs-material>=9.0",
            "mkdocstrings[python]>=0.21",
            "pymdown-extensions>=8.0",
            "mkdocs-awesome-pages-plugin",
        ],
    },
)
