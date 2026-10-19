"""Physical byte ranges: clipped unions and overlap totals, independent of CPU aliases."""
import heapq
import math


def union(ranges, size):
    if type(size) is not int or size <= 0:
        return []
    spans = sorted((max(0, low), min(size, low + count)) for low, count in ranges
                   if type(low) is int and type(count) is int and count > 0 and low < size and low + count > 0)
    merged = []
    for low, high in spans:
        if merged and low <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(high, merged[-1][1]))
        else:
            merged.append((low, high))
    return merged


def length(spans):
    return sum(high - low for low, high in spans)


def overlap(left, right):
    a = b = count = 0
    while a < len(left) and b < len(right):
        low, high = max(left[a][0], right[b][0]), min(left[a][1], right[b][1])
        count += max(0, high - low)
        if left[a][1] < right[b][1]:
            a += 1
        else:
            b += 1
    return count


def acceptance_timeline(ranges, size, limit=128):
    """Attribute each current byte to its earliest stored acceptance date, with a bounded chart."""
    starts = []
    for low, count, when in ranges:
        clipped = union([(low, count)], size)
        if not clipped:
            continue
        when = when if type(when) in (float, int) and math.isfinite(when) and when > 0 else 0
        starts.append((*clipped[0], when))
    starts.sort()
    boundaries = sorted({point for low, high, _when in starts for point in (low, high)})
    heap, gains, index = [], {}, 0
    for low, high in zip(boundaries, boundaries[1:]):
        while index < len(starts) and starts[index][0] <= low:
            _start, end, when = starts[index]
            heapq.heappush(heap, (when, end, index)); index += 1
        while heap and heap[0][1] <= low:
            heapq.heappop(heap)
        if heap:
            gains[heap[0][0]] = gains.get(heap[0][0], 0) + high - low
    baseline = gains.pop(0, 0)
    dates, total, points = sorted(gains), baseline, []
    stride = max(1, math.ceil(len(dates) / limit))
    for index, when in enumerate(dates):
        total += gains[when]
        if (index + 1) % stride == 0 or index == len(dates) - 1:
            points.append([when, total])
    return {'baseline_bytes': baseline, 'points': points, 'bytes': total, 'truncated': len(dates) > limit,
            'scope': 'current stored references by acceptance date; not complete historical coverage'}
