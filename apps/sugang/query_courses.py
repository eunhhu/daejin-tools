#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daejin University Course & Seat Inspector CLI (대진대학교 실시간 과목 및 잔여석 조회 도구)
====================================================================================
"""

import sys
from sugang import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Default behavior: show current status & open courses
        sys.argv.append("status")
    main()
