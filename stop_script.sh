#!/bin/bash
for KILLPID in `ps ax | grep 'translator_bot' | awk '{print $1;}'`; do
kill -9 $KILLPID;
done