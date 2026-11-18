"""Expose the resident gate buffers to the separately dispatched precision profiles."""

from r322_resident_weights_v1 import GATE_BYTES
from r328_neighbor_weights_v1 import CELLS, GATE_BLOCKS_PER_BANK, STRIPES


def spans(first, count):
    """Map one contiguous stripe interval to exact retained bank subranges."""
    limit = CELLS * STRIPES
    if count < 1 or first < 0 or first + count > limit:
        raise ValueError('Invalid resident gate stripe interval')
    stop = first + count
    result = []
    for block in range(first // GATE_BLOCKS_PER_BANK, (stop - 1) // GATE_BLOCKS_PER_BANK + 1):
        start = block * GATE_BLOCKS_PER_BANK
        offset = max(first, start) - start
        length = min(stop, start + GATE_BLOCKS_PER_BANK) - start - offset
        result.append((block, offset * GATE_BYTES, length * GATE_BYTES))
    assert sum(length for _, _, length in result) == count * GATE_BYTES
    return result


def segmented_task(endpoint, blocks, first, count):
    from aie.dialects.aie import EndOp, bds, dma_bd, next_bd
    from aie.dialects.aiex import dma_configure_task, dma_configure_task_for
    from aie.iron.dataflow.tile_dma import TileDmaTask
    from aie.iron.runtime._context import active_sequence

    parts = spans(first, count)
    active = active_sequence()
    for block, _, _ in parts:
        buffer = blocks[block]
        assert buffer.tile.row == endpoint.tile.row == 1 and abs(buffer.tile.col - endpoint.tile.col) <= 1
        active.resolve_in_device(buffer)
    if endpoint.symbol is None:
        op = dma_configure_task(endpoint.tile.op, endpoint.direction, endpoint.channel, issue_token=True, repeat_count=0)
    else:
        op = dma_configure_task_for(endpoint.symbol, issue_token=True, repeat_count=0)
    with bds(op) as regions:
        for index, (block, offset, length) in enumerate(parts):
            with regions[index]:
                dma_bd(blocks[block].op, offset=offset, transfer_len=length)
                if index + 1 == len(parts):
                    EndOp()
                else:
                    next_bd(regions[index + 1])
    return TileDmaTask(endpoint, op.result)


def gru_sequence(cells, batches, signature, request_endpoint, h_host, matrices, control, name):
    from aie.helpers.taplib import TensorAccessPattern
    from aie.iron import Runtime, TaskGroup
    from r210_gru_entries_v1 import FRAME_WORDS, H_WORDS, PAIR_WORDS

    assert (cells, batches) in ((1, 1), (2, 1), (2, 2))
    request_words = FRAME_WORDS if cells == 1 else PAIR_WORDS
    output_words = cells * H_WORDS
    first = 0 if cells == 1 else STRIPES
    count = STRIPES * cells * batches
    shape = (6208,)

    def sequence(x, _state, _intra, _tail, y, request, output, payloads, controls):
        tasks = []
        for batch in range(batches):
            for rtp, _fence in controls:
                rtp[1] = cells
            for _rtp, fence in controls:
                fence.set(1)
            group = TaskGroup()
            request.fill(x, tap=TensorAccessPattern(shape, batch * request_words, [request_words], [1]),
                         group=group, wait=True)
            if batch == 0:
                tasks = [segmented_task(flow.endpoint(flow.src), buffers, first, count).start()
                         for matrix in payloads for flow, buffers in zip(matrix.outbounds, matrix.gates, strict=True)]
            output.drain(y, tap=TensorAccessPattern(shape, batch * output_words, [output_words], [1]),
                         group=group, wait=True)
            group.finish()
        for task in tasks:
            task.await_()
            task.free()

    runtime = Runtime(sequence, [*signature, request_endpoint, h_host, matrices, control], name=name)
    for matrix in matrices:
        for flow in matrix.outbounds:
            runtime.add_flow(flow)
    return runtime


def gru_entry(cells, signature, request, output, matrices, control):
    assert cells in (1, 2)
    return gru_sequence(cells, 1, signature, request, output, matrices, control, 'gru' if cells == 1 else 'gru_pair')


def dual_entry(signature, request, output, matrices, control):
    return gru_sequence(2, 2, signature, request, output, matrices, control, 'gru_dual')
