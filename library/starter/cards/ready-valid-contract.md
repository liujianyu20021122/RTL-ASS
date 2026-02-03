<!-- SPDX-License-Identifier: Apache-2.0 -->
# One-entry ready/valid register contract

A transfer occurs only on a rising edge where `valid && ready` is true. While an output item is valid and the receiver deasserts `ready`, the producer-facing `ready` is low and the output payload remains stable. A simultaneous dequeue and enqueue may replace the held item without inserting a bubble.

The example uses active-low synchronous reset, one item of storage, combinational upstream backpressure, one-cycle storage latency, and one transfer per cycle at full throughput. These choices are part of the example contract, not universal ready/valid rules.
