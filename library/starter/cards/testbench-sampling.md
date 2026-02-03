<!-- SPDX-License-Identifier: Apache-2.0 -->
# Testbench sampling pattern

Drive ready/valid stimulus away from the active edge, decide acceptance from the values present at the active edge, and sample nonblocking-assignment results in a later simulation region. The starter testbench drives on the falling edge and checks one time unit after the rising edge to make the intended phase explicit.

This small pattern is deterministic rather than a substitute for randomized verification. Extend it with a transaction scoreboard, parameter corners, reset interruption, coverage, and checker mutation when the design risk warrants them.
