"""Serve all GRU coefficients directly from three adjacent XDNA2 memory tiles."""

from dataclasses import dataclass

from r313_tail_routes_v1 import (HOT_SIDE, INPUT_WORDS, OUTPUT_WORDS, PACKET_WORDS,
                                 REQUEST_BASE, SIDE_WORDS, destinations, validate_layout)
from r322_resident_weights_v1 import (BANK_BYTES, GATE_BYTES, GATES, MATRIX_BYTES, ROOTS,
                                     STRIPES, STRIPE_BYTES, WORKER_COLS)


ENTRIES = ('front_and_encoder', 'recurrent_tail_0', 'recurrent_tail_1')
CELLS = 5
GATE_BLOCKS_PER_BANK = 3
BANK_SIZE = 65536
MEMTILE_BYTES = 8 * BANK_SIZE
PACK_OFFSET = BANK_SIZE - GATE_BLOCKS_PER_BANK * GATE_BYTES
EGRESS_COLS = ((0, 1, 2), (5, 6, 7))
WEIGHT_COLS = ((0, 2, 1), (6, 5, 7))


@dataclass
class Matrix:
    memory: object
    outbounds: tuple
    gates: tuple


def gate_payload(packed, side, gate):
    assert len(packed) == BANK_BYTES and 0 <= side < 2 and 0 <= gate < GATES
    # Packed DDR order was encoder, two decoder cells per source and parity group,
    # then the final two decoder cells per source. Preserve each gate's FIFO order.
    indices = (side, 2 + 2 * side, 3 + 2 * side, 6 + 2 * side, 7 + 2 * side)
    offsets = [index * MATRIX_BYTES + stripe * STRIPE_BYTES + gate * GATE_BYTES
               for index in indices for stripe in range(STRIPES)]
    return tuple(b''.join(packed[offset:offset + GATE_BYTES]
                         for offset in offsets[start:start + GATE_BLOCKS_PER_BANK])
                 for start in range(0, CELLS * STRIPES, GATE_BLOCKS_PER_BANK))


def matrix_graph(side, make_type):
    import os
    from pathlib import Path

    import numpy as np
    from aie.dialects._aie_enum_gen import DMAChannelDir
    from aie.iron import Acquire, Bd, Buffer, DmaChannel, Flow, Lock, Release, TileDma
    from aie.iron.device import Tile

    from r176_checkpoint_common_v2 import P, read, sha

    model = int(os.environ['R277_MODEL'])
    model_row, = [row for row in read(P / 'R279_BF16_NATIVE_REGISTRY_V1.json')['models'] if row['model'] == model]
    weight = model_row['weight_bank']
    path = Path(weight['path'])
    assert sha(path) == weight['sha256'] and path.stat().st_size == weight['bytes'] == BANK_BYTES
    packed = path.read_bytes()
    outbounds, inputs, gates = [], [], []
    for gate, col in enumerate(WORKER_COLS[side]):
        egress = Tile(EGRESS_COLS[side][gate], 1)
        weight_tile = Tile(WEIGHT_COLS[side][gate], 1)
        blocks = []
        for bank, payload in enumerate(gate_payload(packed, side, gate), start=1):
            blocks.append(Buffer(make_type(len(payload)), tile=weight_tile, name=f'r327_weight_{side}_{gate}_{bank}',
                                 address=bank * BANK_SIZE + PACK_OFFSET, mem_bank=bank,
                                 initial_value=np.frombuffer(payload, dtype=np.uint8).copy()))
        gates.append(tuple(blocks))
        worker = Tile(col, 5)
        flow = Flow(egress, worker, name=f'r327_weight_gate_{side}_{gate}')
        buffer = Buffer(make_type(GATE_BYTES), tile=worker, name=f'r322_coef_{side}_{gate}')
        empty = Lock(tile=worker, init=1, name=f'r322_gate_empty_{side}_{gate}')
        full = Lock(tile=worker, init=0, name=f'r322_gate_full_{side}_{gate}')
        receive = Bd(buffer, acquires=[Acquire(empty)], releases=[Release(full)])
        dma = TileDma(worker, [DmaChannel(DMAChannelDir.S2MM, flow.endpoint(worker), [receive])])
        outbounds.append(flow)
        inputs.append((worker, buffer, empty, full, dma))
    # Keep the GRU's existing gate output aggregation and states on their original tiles.
    return Matrix(Tile(ROOTS[side], 1), tuple(outbounds), tuple(gates)), tuple(inputs)


def neighbor_task(endpoint, blocks):
    """Emit the legal west/local/east DMA windows via the low-level AIE dialect."""
    from aie.dialects.aie import EndOp, bds, dma_bd, next_bd
    from aie.dialects.aiex import dma_configure_task, dma_configure_task_for
    from aie.iron.dataflow.tile_dma import TileDmaTask
    from aie.iron.runtime._context import active_sequence

    # DmaEndpoint.task currently only accepts buffers placed on the same tile.
    # AIEDMATasksToNPU uses getMemLocalBaseAddress to encode each adjacent window.
    active = active_sequence()
    for buffer in blocks:
        assert buffer.tile.row == endpoint.tile.row == 1 and abs(buffer.tile.col - endpoint.tile.col) <= 1
        active.resolve_in_device(buffer)
    if endpoint.symbol is None:
        op = dma_configure_task(endpoint.tile.op, endpoint.direction, endpoint.channel,
                                issue_token=True, repeat_count=0)
    else:
        op = dma_configure_task_for(endpoint.symbol, issue_token=True, repeat_count=0)
    with bds(op) as regions:
        for index, buffer in enumerate(blocks):
            with regions[index]:
                dma_bd(buffer.op)
                if index + 1 == len(blocks):
                    EndOp()
                else:
                    next_bd(regions[index + 1])
    return TileDmaTask(endpoint, op.result)


def recurrent(x, y, request, output, matrices, side, controls, bank):
    from aie.helpers.taplib import TensorAccessPattern
    from aie.iron import TaskGroup
    from r277_recurrent_v1 import BRIDGE_MODE

    validate_layout()
    for ctrl, _ in controls:
        ctrl[0] = BRIDGE_MODE
        ctrl[1] = 1
    for _, fence in controls:
        fence.set(1)

    encoder, *decoder = destinations(bank)
    group = TaskGroup()
    request.fill(x, tap=TensorAccessPattern((INPUT_WORDS,), REQUEST_BASE, [PACKET_WORDS], [1]), group=group, wait=True)
    tasks = [neighbor_task(flow.endpoint(flow.src), blocks).start()
             for matrix in matrices for flow, blocks in zip(matrix.outbounds, matrix.gates, strict=True)]
    output.drain(y, tap=TensorAccessPattern((OUTPUT_WORDS,), encoder.first, [encoder.words], [1]), group=group, wait=True)
    side.drain(y, tap=TensorAccessPattern((OUTPUT_WORDS,), HOT_SIDE, [SIDE_WORDS], [1]), group=group, wait=True)
    group.finish()

    group = TaskGroup()
    for span in decoder:
        output.drain(y, tap=TensorAccessPattern((OUTPUT_WORDS,), span.first, [span.words], [1]), group=group, wait=True)
    group.finish()
    for task in tasks:
        task.await_()
        task.free()
