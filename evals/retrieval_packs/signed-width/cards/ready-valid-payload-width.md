# Parameterized ready/valid payload widths

Treat a ready/valid payload as an opaque vector whose declared width must remain identical across the producer, storage element, and consumer. While `valid` is asserted and `ready` is deasserted, hold both the payload bits and the validity state stable. A parameter change must alter the complete payload path without changing handshake latency or capacity.

Check width-one and a representative wider value, reset while empty, acceptance into an empty stage, backpressure stability, and simultaneous dequeue/enqueue. This guidance concerns payload transport and handshake state. It does not define signed arithmetic expression sizing, saturation thresholds, or numeric comparison rules.
