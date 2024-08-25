from setuptools import setup, find_packages

setup(
    name="ezdvm",
    version="0.1.0",
    author="Dustin Dannenhauer",
    author_email="dustin@dvmdash.live",
    description="A simple DVM (Data Vending Machine) implementation for nostr",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/dtdannen/ezdvm",
    packages=find_packages(),
    install_requires=[
        "nostr_sdk",
        "loguru",
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.12",
)