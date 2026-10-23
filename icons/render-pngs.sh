#!/bin/sh
# Render the icon's PNG sizes from its SVG. Every edge of the icon falls on a
# whole unit of its 16-unit grid, so at these sizes (multiples of 16) no pixel
# comes out partly transparent. Needs ImageMagick with its librsvg delegate.
cd "$(dirname "$0")/hicolor" || exit 1
for n in 16 32 48 64 128 256; do
    mkdir -p "${n}x${n}/apps"
    magick -background none -density $((96 * n / 16)) scalable/apps/gridlet.svg \
        -strip "PNG32:${n}x${n}/apps/gridlet.png"
done
