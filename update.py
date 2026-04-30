#!/usr/bin/env python3
import sys
print("TEST 1", flush=True)
sys.stdout.flush()
print("TEST 2")
import json
print("TEST 3")
import feedparser
print("TEST 4 - feedparser OK")
import requests
print("TEST 5 - requests OK")
print("TOUT OK")
