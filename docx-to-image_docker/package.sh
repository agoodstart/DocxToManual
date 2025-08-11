#!/bin/bash
set -e

echo "Installing dependencies into ./python..."
/usr/bin/pip3.13 install -r requirements.txt -t python

echo "Creating layer.zip (only dependencies)..."
cd python && cd .. && zip -r9 /opt/output/layer.zip python

echo "Creating function.zip (only function code)..."
zip -r9 /opt/output/function.zip lambda_function.py

echo "Done. Files written to /opt/output"