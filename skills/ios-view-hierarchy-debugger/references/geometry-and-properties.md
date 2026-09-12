# Geometry, properties, and causal interpretation

Use this reference when answering a question about size, position, appearance, layout, visibility, or interaction. Ask for the specific fields required by the hypothesis; the bundled capture's actual field inventory is in `lldb-capture.md`.

## Coordinate spaces are part of every measurement

- `bounds` describes a view's local coordinate rectangle. Its origin can be nonzero, especially in scrolling systems.
- `frame` describes a rectangle in the superview's coordinate system. UIKit does not give `frame` reliable semantics under a nonidentity transform. Use bounds plus converted corners and the transform chain in that case.
- `center` is in the superview's space. CALayer `position` is in its superlayer's space and relates to `anchorPoint`, not necessarily a top-left origin.
- A converted screen-space rectangle encloses the transformed shape. It may include empty corners around a rotated view; it is not an exact hit region.
- Convert all four corners of `bounds` to the owning window's screen coordinate space to obtain a quad. Retain local, window, screen, and presentation evidence separately. Never mix model-layer and presentation-layer transforms within one chain.
- UIKit and AX coordinates generally use logical points. Screenshot pixels use image dimensions. Record screen ID, logical screen bounds, orientation, image size, and conversion. Do not assume all images use 2x or 3x or that every window belongs to the main screen.

For an image that covers the same oriented full-screen rectangle, a basic mapping is:

```text
pixelX = (screenX - screenBounds.x) * imageWidth / screenBounds.width
pixelY = (screenY - screenBounds.y) * imageHeight / screenBounds.height
```

Use this only after verifying the screen and image have the same orientation, crop, and viewport. A screenshot of a window, a resized preview, an external display, or a crop requires its own mapping. A point query in `ui_evidence.py` expects screen points, not pixels.

### Example

A screenshot is 1170 x 2532 pixels and represents a 390 x 844 point screen. The visible position at pixel (630,1290) maps to (210,430) points. If the image is displayed at a different preview size, first map from preview coordinates to the image's original pixel dimensions. This ratio is an example, not a device assumption.

## Which facts answer which questions

| Question | Request | Interpret carefully |
|---|---|---|
| Why is it the wrong size? | Bounds, intrinsic size, width/height constraints, size proposal/result if authored SwiftUI, hugging/compression, stack configuration, sibling allocation | Negative intrinsic dimensions can mean no intrinsic metric; a narrow label alone does not prove bad constraints |
| Why is it shifted? | Parent bounds origin, screen quad, transform chain, safe area, margins, scroll offset/insets, alignment constraints | Scroll movement and transforms can change screen position without changing the local frame |
| Why is it clipped? | Clipping ancestors, ancestor quads, masks/corner radius, scroll viewport, crop | Being outside a parent does not imply clipping unless the relevant clipping/mask behavior applies |
| Why is text truncated? | Visible crop, label bounds, font descriptor/size, number of lines, line break mode, intrinsic size, compression, preferred maximum layout width | Intrinsic width is not always rendered line width; attributed text and custom text layout need their own evidence |
| Why is its color wrong? | Resolved UIColor under the node's trait collection, alpha chain, layer colors/gradients, overlays, pixels | A dynamic semantic color and a composited final pixel are different facts; not all colors convert to RGB |
| Why is it untappable? | AX hittability, control enabled, interaction/hidden/alpha ancestor state, target point, window order, targeted hit test, gestures | A disabled UIControl can participate in hit testing; native hit testing does not guarantee gesture delivery or app action success |
| Why is state stale? | Control values, selection, first responder, visible crop, timestamp, navigation/fixture state, authored scalar state | Exposed UI values do not reveal the full data model; avoid a stale snapshot diagnosis until fresh observations agree |
| Why does a shadow/blur cost time? | Public layer configuration plus a matching Instruments trace | A mask, shadow, or rasterization flag suggests work; it does not measure an offscreen pass or hitch |

## Auto Layout evidence

For the selected view and its relevant ancestors, collect installed constraints and `constraintsAffectingLayout(for:)` separately for horizontal and vertical axes where available. A constraint may be installed on a common ancestor, so `selectedView.constraints` is insufficient.

Represent an equation as `firstItem.firstAttribute relation multiplier * secondItem.secondAttribute + constant`, with item identity, guide owner, identifier, priority, and active state. Preserve numerical attribute/relation values if the adapter cannot map them confidently. A missing second item is valid for a dimension constant. Layout guides need owning-view context.

Read `hasAmbiguousLayout`, content hugging and compression resistance, intrinsic size, autoresizing-mask translation, safe area, margins, and UIStackView distribution/alignment/spacing when applicable. Ambiguity is a runtime fact; a conflict needs contemporaneous unsatisfiable-constraint output or equivalent evidence. Do not reconstruct Apple's complete constraint-solver decisions from one failed equation.

Capture before any `layoutIfNeeded`, `setNeedsLayout`, priority mutation, or ambiguity exercise. Those calls can change the bug. If the user requests an experiment, label its resulting capture and retain the original checkpoint.

## Style and class-specific properties

Read only public getters or an existing allowlisted debug adapter. Do not enumerate arbitrary application selectors or serialize `description` of arbitrary model objects.

- UIView: hidden, alpha, opaque, clipping, interaction, content mode, autoresizing behavior, traits, background/tint colors, accessibility identifier, and first responder.
- UILabel/text: font name and point size, descriptor traits where exposed, alignment, line count and break mode, enabled/selected editing state as applicable. Content text is optional and must follow redaction rules. Secure fields must never emit their actual text or accessibility value.
- UIControl subclasses: enabled/selected/highlighted and relevant typed values, such as switch state, slider range/value, and segmented selection. These are snapshots, not proof the action was delivered.
- UIScrollView: content size/offset, content and adjusted insets, viewport bounds, dragging/decelerating/zoom state when exposed. Cell reuse requires a stable model/component identity, not only a pointer or index path.
- UIImageView/images: content mode, image dimensions/scale, tint and configuration where available. The original asset name may not survive runtime loading.
- CALayer: frame/bounds/position/anchor, zPosition, transform, opacity, background/border/corner, shadow, mask, rasterization, and presentation state. The view's backing layer properties do not imply that all descendant layers have been captured.

Resolve `UIColor` with that view's current trait collection. Preserve whether conversion succeeded and the color space/provider representation. A null background can mean no explicit background, not opaque black. Alpha from parent views, masks, effects, gradients, images, extended color spaces, and other windows can alter pixels.

## Visibility has several answers

Keep these independent when available:

```text
localHidden / ancestorHidden
localAlpha / effectiveAlpha
nonEmptyBounds / attachedToWindow
intersectsViewport / clippedByAncestors
AXExists / AXHittable
nativeHitTestWinnerAtPoint
pixelOcclusionEstimate
enabled / userInteractionEnabled
```

Unknown facets remain unknown. Even a complete rectangle overlap test is only geometric. Masks, nonrectangular content, transforms, z ordering, transparent overlays, and other windows complicate occlusion. A custom `hitTest` override can execute app code; use a targeted query only when its diagnostic value justifies that execution. Inspect gestures separately when a hit-test winner is correct but delivery fails.

## Attribution and timing

A current LLDB stack tells where execution is paused. It does not show the historical call that created a view, assigned a color, or produced the current state. For those questions use source search by stable identifiers/class, an authored source registry, a relevant breakpoint followed by reproduction, or allocation stack evidence enabled before allocation. Only set future breakpoints or rerun the scenario if it advances the user's investigation.

While an animation runs, model geometry describes the requested state; a presentation layer approximates the displayed intermediate state. A process pause may not freeze every compositor or out-of-process surface. Record timestamps and uncertainty. Do not profile app performance while the inspection debugger is attached and then treat the result as ordinary run performance.
