#!/bin/bash

dnf install -y libusb
dnf install -y python2
python2 -m ensurepip --no-default-pip
python2 -m pip install --upgrade setuptools 
dnf install -y libusb
