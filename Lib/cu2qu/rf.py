# Copyright 2015 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Converts cubic bezier curves to quadratic splines.

Conversion is performed such that the quadratic splines keep the same end-curve
tangents as the original cubics. The approach is iterative, increasing the
number of segments for a spline until the error gets below a bound.

Respective curves from multiple fonts will be converted at once to ensure that
the resulting splines are interpolation-compatible.
"""


from robofab.objects.objectsRF import RSegment
from cu2qu.geometry import Point, curve_to_quadratic, curves_to_quadratic


_zip = zip
def zip(*args):
    """Ensure each argument to zip has the same length."""

    if len(set(len(a) for a in args)) != 1:
        msg = 'Args to zip in cu2qu should have equal lengths: '
        raise ValueError(msg + ' '.join(str(a) for a in args))
    return _zip(*args)


def fonts_to_quadratic(*fonts, **kwargs):
    """Convert the curves of a collection of fonts to quadratic.

    All curves will be converted to quadratic at once, ensuring interpolation
    compatibility. If this is not required, calling fonts_to_quadratic with one
    font at a time may yield slightly more optimized results.
    """

    max_n = kwargs.get('max_n', 10)
    max_err = kwargs.get('max_err', 0.0025)
    max_errors = [f.info.unitsPerEm * max_err for f in fonts]
    report = kwargs.get('report', {})
    dump_report = kwargs.get('dump_report', False)

    for glyph in FontCollection(fonts):
        glyph_to_quadratic(glyph, max_errors, max_n, report)

    if dump_report:
        spline_lengths = report.keys()
        spline_lengths.sort()
        print 'New spline lengths:\n%s\n' % (
            '\n'.join('%s: %d' % (l, report[l]) for l in spline_lengths))
    return report


def glyph_to_quadratic(glyph, max_err, max_n, report):
    """Convert a glyph's curves to quadratic, in place."""

    for contour in glyph:
        segments = []
        for i in range(len(contour)):
            segment = contour[i]
            if segment.type == 'curve':
                segments.append(segment_to_quadratic(
                    contour, i, max_err, max_n, report))
            else:
                segments.append(segment)
        replace_segments(contour, segments)


def segment_to_quadratic(contour, segment_id, max_err, max_n, report):
    """Return a quadratic approximation of a cubic segment."""

    segment = contour[segment_id]
    if segment.type != 'curve':
        raise TypeError('Segment type not curve')

    # assumes that a curve type will always be proceeded by another point on the
    # same contour
    prev_segment = contour[segment_id - 1]
    points = points_to_quadratic(prev_segment.points[-1], segment.points[0],
                                 segment.points[1], segment.points[2],
                                 max_err, max_n)

    if isinstance(points[0][0], float):  # just one spline
        n = str(len(points))
        points = points[1:]

    else:  # collection of splines
        n = str(len(points[0]))
        points = [p[1:] for p in points]

    report[n] = report.get(n, 0) + 1
    return as_quadratic(segment, points)


def points_to_quadratic(p0, p1, p2, p3, max_err, max_n):
    """Return a quadratic spline approximating the cubic bezier defined by these
    points (or collections of points).
    """

    if hasattr(p0, 'x'):
        curve = [Point([i.x, i.y]) for i in [p0, p1, p2, p3]]
        return curve_to_quadratic(curve, max_err, max_n)

    curves = [[Point([i.x, i.y]) for i in p] for p in zip(p0, p1, p2, p3)]
    return curves_to_quadratic(curves, max_err, max_n)


def replace_segments(contour, segments):
    """Replace the segments of a given contour."""

    try:
        contour.replace_segments(segments)
        return
    except AttributeError:
        pass

    while len(contour):
        contour.removeSegment(0)
    for s in segments:
        contour.appendSegment(s.type, [(p.x, p.y) for p in s.points], s.smooth)


def as_quadratic(segment, points):
    """Return a new segment with given points and type qcurve."""

    try:
        return segment.as_quadratic(points)
    except AttributeError:
        return RSegment(
            'qcurve', [[int(round(i)) for i in p] for p in points], segment.smooth)


class FontCollection:
    """A collection of fonts, or font components from different fonts.

    Behaves like a single instance of the component, allowing access into
    multiple fonts simultaneously for purposes of ensuring interpolation
    compatibility.
    """

    def __init__(self, fonts):
        self.init(fonts, GlyphCollection)

    def __getitem__(self, key):
        return self.children[key]

    def __len__(self):
        return len(self.children)

    def __str__(self):
        return str(self.instances)

    def init(self, instances, child_collection_type, get_children=None):
        self.instances = instances
        children_by_instance = map(get_children, self.instances)
        self.children = map(child_collection_type, zip(*children_by_instance))


class GlyphCollection(FontCollection):
    def __init__(self, glyphs):
        self.init(glyphs, ContourCollection)
        self.name = glyphs[0].name


class ContourCollection(FontCollection):
    def __init__(self, contours):
        self.init(contours, SegmentCollection)

    def replace_segments(self, segment_collections):
        segments_by_contour = zip(*[s.instances for s in segment_collections])
        for contour, segments in zip(self.instances, segments_by_contour):
            replace_segments(contour, segments)


class SegmentCollection(FontCollection):
    def __init__(self, segments):
        self.init(segments, None, lambda s: s.points)
        self.points = self.children
        self.type = segments[0].type

    def as_quadratic(self, new_points=None):
        points = new_points or self.children
        return SegmentCollection([
            as_quadratic(s, pts) for s, pts in zip(self.instances, points)])
