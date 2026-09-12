"""LLDB command: ui_capture /absolute/new.json [--max-nodes 2000] [--max-depth 40].

Import in LLDB with `command script import /absolute/path/lldb_ui.py`.
The expression uses public UIKit/Core Animation APIs; it does not attach/resume.
"""
import argparse
import datetime
import json
import os
import shlex
import uuid

try:
    import lldb
except ImportError:  # Allows offline syntax/SDK validation.
    lldb = None


# Standalone clang validation only. LLDB must import SDK modules as persistent
# declarations before capture; its wrapper prefix does not use those search paths.
PREFIX = """#import <UIKit/UIKit.h>
#import <QuartzCore/QuartzCore.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
"""

# Kept as one expression so the main-thread assertion precedes all UIKit reads.
# Arguments are fixed numeric limits and generated ASCII identifiers only.
CAPTURE_EXPRESSION = r'''({
    char *result = (char *)0;
    if ([NSThread isMainThread]) {
      @autoreleasepool {
        NSInteger maxNodes = __MAX_NODES__, maxDepth = __MAX_DEPTH__;
        NSUInteger maxBytes = __MAX_BYTES__;
        id (^num)(double) = ^id(double x) { return isfinite(x) ? @(x) : (id)[NSNull null]; };
        NSDictionary *(^point)(CGPoint) = ^NSDictionary *(CGPoint p) { return @{ @"x":num(p.x), @"y":num(p.y) }; };
        NSDictionary *(^size)(CGSize) = ^NSDictionary *(CGSize s) { return @{ @"width":num(s.width), @"height":num(s.height) }; };
        NSDictionary *(^rect)(CGRect) = ^NSDictionary *(CGRect r) {
          if (CGRectIsInfinite(r) || CGRectIsNull(r)) return @{ @"x":[NSNull null], @"y":[NSNull null], @"width":[NSNull null], @"height":[NSNull null], @"finite":@NO, @"specialValue":CGRectIsInfinite(r) ? @"CGRectInfinite" : @"CGRectNull" };
          return @{ @"x":num(r.origin.x), @"y":num(r.origin.y), @"width":num(r.size.width), @"height":num(r.size.height), @"finite":@(isfinite(r.origin.x)&&isfinite(r.origin.y)&&isfinite(r.size.width)&&isfinite(r.size.height)) };
        };
        NSDictionary *(^insets)(UIEdgeInsets) = ^NSDictionary *(UIEdgeInsets i) { return @{ @"top":num(i.top), @"left":num(i.left), @"bottom":num(i.bottom), @"right":num(i.right) }; };
        NSString *(^ident)(id) = ^NSString *(id x) { return x ? [NSString stringWithFormat:@"v:%p", x] : @""; };
        NSDictionary *(^color)(UIColor *, UITraitCollection *) = ^NSDictionary *(UIColor *c, UITraitCollection *traits) {
          if (!c) return @{ @"available":@NO, @"reason":@"nil" };
          UIColor *resolved = [c resolvedColorWithTraitCollection:traits];
          CGFloat r=0,g=0,b=0,a=0,w=0;
          if ([resolved getRed:&r green:&g blue:&b alpha:&a]) return @{ @"available":@YES, @"space":@"resolved-rgb", @"r":num(r), @"g":num(g), @"b":num(b), @"a":num(a) };
          if ([resolved getWhite:&w alpha:&a]) return @{ @"available":@YES, @"space":@"resolved-gray", @"white":num(w), @"a":num(a) };
          return @{ @"available":@NO, @"reason":@"non-component-color-or-pattern" };
        };
        NSDictionary *(^item)(id) = ^NSDictionary *(id obj) {
          NSObject *x=(NSObject *)obj;
          if (!x) return @{ @"kind":@"none" };
          if ([x isKindOfClass:[UIView class]]) return @{ @"kind":@"view", @"id":ident(x), @"class":NSStringFromClass([x class]) };
          if ([x isKindOfClass:[UILayoutGuide class]]) {
            UILayoutGuide *g=(UILayoutGuide *)x;
            return @{ @"kind":@"layoutGuide", @"id":[NSString stringWithFormat:@"g:%p",g], @"identifier":g.identifier ?: @"", @"owningViewId":ident(g.owningView), @"layoutFrame":rect(g.layoutFrame) };
          }
          return @{ @"kind":@"other", @"class":NSStringFromClass([x class]), @"id":[NSString stringWithFormat:@"o:%p",x] };
        };
        NSDictionary *(^constraint)(NSLayoutConstraint *) = ^NSDictionary *(NSLayoutConstraint *c) {
          return @{ @"id":[NSString stringWithFormat:@"c:%p",c], @"identifier":c.identifier ?: @"", @"firstItem":item(c.firstItem), @"secondItem":item(c.secondItem), @"firstAttribute":@(c.firstAttribute), @"secondAttribute":@(c.secondAttribute), @"relation":@(c.relation), @"multiplier":num(c.multiplier), @"constant":num(c.constant), @"priority":num(c.priority), @"active":@(c.active) };
        };
        NSArray *(^constraints)(NSArray *, NSUInteger) = ^NSArray *(NSArray *list, NSUInteger limit) {
          NSMutableArray *out=[NSMutableArray array];
          for (NSLayoutConstraint *c in list) { if(out.count>=limit) break; [out addObject:constraint(c)]; }
          return out;
        };
        NSMutableArray *windows=[NSMutableArray array], *windowInfo=[NSMutableArray array];
        UIApplication *app=[UIApplication sharedApplication];
        for (UIScene *scene in app.connectedScenes) {
          if (![scene isKindOfClass:[UIWindowScene class]]) continue;
          UIWindowScene *ws=(UIWindowScene *)scene;
          for (UIWindow *w in ws.windows) {
            if ([windows containsObject:w]) continue;
            [windows addObject:w];
            [windowInfo addObject:@{ @"id":ident(w), @"screenBounds":rect(w.screen.bounds), @"screenScale":num(w.screen.scale), @"screenNativeScale":num(w.screen.nativeScale), @"orientation":@(ws.interfaceOrientation), @"sceneActivationState":@(scene.activationState), @"keyWindow":@(w.isKeyWindow), @"windowLevel":num(w.windowLevel) }];
          }
        }
        // Legacy applications may not use UIScene. This is a public deprecated fallback.
        if (windows.count==0) {
          for (UIWindow *w in app.windows) {
            [windows addObject:w];
            [windowInfo addObject:@{ @"id":ident(w), @"screenBounds":rect(w.screen.bounds), @"screenScale":num(w.screen.scale), @"screenNativeScale":num(w.screen.nativeScale), @"orientation":@0, @"sceneActivationState":@0, @"keyWindow":@(w.isKeyWindow), @"windowLevel":num(w.windowLevel) }];
          }
        }
        NSMutableArray *nodes=[NSMutableArray array], *queue=[NSMutableArray array];
        for (UIWindow *w in windows) [queue addObject:@{ @"view":w, @"window":w, @"depth":@0, @"parent":@"", @"ancestorHidden":@NO, @"ancestorAlpha":@1 }];
        BOOL nodeLimit=NO, depthLimit=NO, constraintLimit=NO;
        NSUInteger cursor=0;
        while (cursor<queue.count) {
          if (nodes.count >= (NSUInteger)maxNodes) { nodeLimit=YES; break; }
          NSDictionary *entry=queue[cursor++]; UIView *v=entry[@"view"]; UIWindow *w=entry[@"window"]; NSInteger depth=[(NSNumber *)entry[@"depth"] integerValue];
          CGRect b=v.bounds; CGAffineTransform t=v.transform;
          CGRect sf=[v convertRect:b toCoordinateSpace:w.screen.coordinateSpace];
          NSArray *quad=@[point([v convertPoint:CGPointMake(CGRectGetMinX(b),CGRectGetMinY(b)) toCoordinateSpace:w.screen.coordinateSpace]),point([v convertPoint:CGPointMake(CGRectGetMaxX(b),CGRectGetMinY(b)) toCoordinateSpace:w.screen.coordinateSpace]),point([v convertPoint:CGPointMake(CGRectGetMaxX(b),CGRectGetMaxY(b)) toCoordinateSpace:w.screen.coordinateSpace]),point([v convertPoint:CGPointMake(CGRectGetMinX(b),CGRectGetMaxY(b)) toCoordinateSpace:w.screen.coordinateSpace])];
          BOOL usableScreenRect = !CGRectIsInfinite(sf) && !CGRectIsNull(sf) && isfinite(sf.origin.x) && isfinite(sf.origin.y) && isfinite(sf.size.width) && isfinite(sf.size.height);
          if (!usableScreenRect) {
            NSDictionary *unknownPoint=@{ @"x":[NSNull null], @"y":[NSNull null] };
            quad=@[unknownPoint,unknownPoint,unknownPoint,unknownPoint];
          }
          CGFloat effectiveAlpha=[(NSNumber *)entry[@"ancestorAlpha"] doubleValue]*v.alpha;
          BOOL ancestorHidden=[(NSNumber *)entry[@"ancestorHidden"] boolValue];
          NSMutableDictionary *props=[@{ @"hidden":@(v.hidden), @"alpha":num(v.alpha), @"opaque":@(v.opaque), @"clipsToBounds":@(v.clipsToBounds), @"userInteractionEnabled":@(v.userInteractionEnabled), @"multipleTouchEnabled":@(v.multipleTouchEnabled), @"firstResponder":@(v.isFirstResponder), @"contentMode":@(v.contentMode), @"tag":@(v.tag), @"backgroundColor":color(v.backgroundColor,v.traitCollection), @"tintColor":color(v.tintColor,v.traitCollection), @"isAccessibilityElement":@(v.isAccessibilityElement), @"accessibilityTraits":@(v.accessibilityTraits), @"accessibilityElementsHidden":@(v.accessibilityElementsHidden), @"accessibilityViewIsModal":@(v.accessibilityViewIsModal), @"effectiveUserInterfaceLayoutDirection":@(v.effectiveUserInterfaceLayoutDirection), @"userInterfaceStyle":@(v.traitCollection.userInterfaceStyle), @"displayScale":num(v.traitCollection.displayScale), @"preferredContentSizeCategory":v.traitCollection.preferredContentSizeCategory ?: @"" } mutableCopy];
          if ([v isKindOfClass:[UILabel class]]) { UILabel *l=(UILabel *)v; props[@"label"]=@{ @"fontName":l.font.fontName ?: @"", @"fontSize":num(l.font.pointSize), @"numberOfLines":@(l.numberOfLines), @"lineBreakMode":@(l.lineBreakMode), @"textAlignment":@(l.textAlignment), @"adjustsFontSizeToFitWidth":@(l.adjustsFontSizeToFitWidth), @"minimumScaleFactor":num(l.minimumScaleFactor), @"textColor":color(l.textColor,v.traitCollection), @"textOmitted":@YES }; }
          if ([v isKindOfClass:[UIControl class]]) { UIControl *c=(UIControl *)v; props[@"control"]=@{ @"enabled":@(c.enabled), @"selected":@(c.selected), @"highlighted":@(c.highlighted), @"state":@(c.state) }; }
          if ([v isKindOfClass:[UITextField class]]) { UITextField *f=(UITextField *)v; props[@"textField"]=@{ @"secureTextEntry":@(f.secureTextEntry), @"editing":@(f.editing), @"textOmitted":@YES, @"fontSize":f.font ? num(f.font.pointSize) : (id)[NSNull null], @"textAlignment":@(f.textAlignment), @"textColor":color(f.textColor,v.traitCollection) }; }
          if ([v isKindOfClass:[UITextView class]]) { UITextView *tv=(UITextView *)v; props[@"textView"]=@{ @"secureTextEntry":@(tv.secureTextEntry), @"editable":@(tv.editable), @"selectable":@(tv.selectable), @"textOmitted":@YES, @"textContainerInset":insets(tv.textContainerInset), @"fontSize":tv.font ? num(tv.font.pointSize) : (id)[NSNull null] }; }
          if ([v isKindOfClass:[UIScrollView class]]) { UIScrollView *s=(UIScrollView *)v; props[@"scroll"]=@{ @"contentOffset":point(s.contentOffset), @"contentSize":size(s.contentSize), @"contentInset":insets(s.contentInset), @"adjustedContentInset":insets(s.adjustedContentInset), @"zoomScale":num(s.zoomScale), @"scrollEnabled":@(s.scrollEnabled), @"dragging":@(s.dragging), @"decelerating":@(s.decelerating), @"tracking":@(s.tracking), @"pagingEnabled":@(s.pagingEnabled) }; }
          NSArray *own=v.constraints, *horizontal=[v constraintsAffectingLayoutForAxis:UILayoutConstraintAxisHorizontal], *vertical=[v constraintsAffectingLayoutForAxis:UILayoutConstraintAxisVertical];
          BOOL ct=own.count>128||horizontal.count>128||vertical.count>128; constraintLimit=constraintLimit||ct;
          CALayer *l=v.layer; CATransform3D lt=l.transform;
          NSMutableDictionary *node=[@{ @"id":ident(v), @"kind":@"view", @"class":NSStringFromClass([v class]), @"windowId":ident(w), @"depth":@(depth), @"geometry":@{ @"frame":rect(v.frame), @"bounds":rect(b), @"center":point(v.center), @"screenFrame":rect(sf), @"screenQuad":quad, @"coordinateSpace":@"screen-points", @"frameCoordinateSpace":@"superview", @"boundsCoordinateSpace":@"local", @"frameReliable":@(CGAffineTransformIsIdentity(t)), @"transform":@{ @"a":num(t.a), @"b":num(t.b), @"c":num(t.c), @"d":num(t.d), @"tx":num(t.tx), @"ty":num(t.ty) } }, @"properties":props, @"layout":@{ @"ambiguous":@(v.hasAmbiguousLayout), @"intrinsicSize":size(v.intrinsicContentSize), @"huggingHorizontal":num([v contentHuggingPriorityForAxis:UILayoutConstraintAxisHorizontal]), @"huggingVertical":num([v contentHuggingPriorityForAxis:UILayoutConstraintAxisVertical]), @"compressionHorizontal":num([v contentCompressionResistancePriorityForAxis:UILayoutConstraintAxisHorizontal]), @"compressionVertical":num([v contentCompressionResistancePriorityForAxis:UILayoutConstraintAxisVertical]), @"translatesAutoresizingMaskIntoConstraints":@(v.translatesAutoresizingMaskIntoConstraints), @"safeAreaInsets":insets(v.safeAreaInsets), @"layoutMargins":insets(v.layoutMargins), @"constraintsAffectingHorizontal":constraints(horizontal,128), @"constraintsAffectingVertical":constraints(vertical,128), @"constraintCounts":@{ @"own":@(own.count), @"horizontal":@(horizontal.count), @"vertical":@(vertical.count) }, @"constraintsTruncated":@(ct) }, @"constraints":constraints(own,128), @"layer":@{ @"class":NSStringFromClass([l class]), @"bounds":rect(l.bounds), @"position":point(l.position), @"anchorPoint":point(l.anchorPoint), @"zPosition":num(l.zPosition), @"opacity":num(l.opacity), @"hidden":@(l.hidden), @"masksToBounds":@(l.masksToBounds), @"cornerRadius":num(l.cornerRadius), @"borderWidth":num(l.borderWidth), @"borderColor":color(l.borderColor ? [UIColor colorWithCGColor:l.borderColor] : nil,v.traitCollection), @"backgroundColor":color(l.backgroundColor ? [UIColor colorWithCGColor:l.backgroundColor] : nil,v.traitCollection), @"shadowOpacity":num(l.shadowOpacity), @"shadowRadius":num(l.shadowRadius), @"shadowOffset":size(l.shadowOffset), @"shadowColor":color(l.shadowColor ? [UIColor colorWithCGColor:l.shadowColor] : nil,v.traitCollection), @"hasShadowPath":@(l.shadowPath!=NULL), @"hasMask":@(l.mask!=nil), @"shouldRasterize":@(l.shouldRasterize), @"rasterizationScale":num(l.rasterizationScale), @"contentsScale":num(l.contentsScale), @"sublayerCount":@(l.sublayers.count), @"animationKeys":l.animationKeys ?: @[], @"transform3D":@[num(lt.m11),num(lt.m12),num(lt.m13),num(lt.m14),num(lt.m21),num(lt.m22),num(lt.m23),num(lt.m24),num(lt.m31),num(lt.m32),num(lt.m33),num(lt.m34),num(lt.m41),num(lt.m42),num(lt.m43),num(lt.m44)] }, @"visibility":@{ @"hiddenSelf":@(v.hidden), @"hiddenByAncestor":@(ancestorHidden), @"effectiveAlpha":num(effectiveAlpha), @"intersectsScreen":@(CGRectIntersectsRect(sf,w.screen.bounds)), @"positiveBounds":@(b.size.width>0&&b.size.height>0), @"occlusion":@"unknown", @"ancestorClippingEvaluated":@NO, @"hitTestEvaluated":@NO }, @"childrenCount":@(v.subviews.count) } mutableCopy];
          if (!usableScreenRect) {
            NSMutableDictionary *visibility=[NSMutableDictionary dictionaryWithDictionary:node[@"visibility"]];
            visibility[@"intersectsScreen"]=[NSNull null];
            node[@"visibility"]=visibility;
          }
          if ([(NSString *)entry[@"parent"] length]) node[@"parentId"]=entry[@"parent"];
          if (v.accessibilityIdentifier.length) node[@"accessibilityIdentifier"]=v.accessibilityIdentifier;
          [nodes addObject:node];
          if (depth>=maxDepth) { if(v.subviews.count) { depthLimit=YES; node[@"childrenTruncated"]=@YES; } }
          else for (UIView *child in v.subviews) {
            if (queue.count >= (NSUInteger)maxNodes + windows.count) { nodeLimit=YES; node[@"childrenTruncated"]=@YES; break; }
            [queue addObject:@{ @"view":child, @"window":w, @"depth":@(depth+1), @"parent":ident(v), @"ancestorHidden":@(ancestorHidden||v.hidden), @"ancestorAlpha":num(effectiveAlpha) }];
          }
        }
        NSMutableDictionary *counts=[NSMutableDictionary dictionary];
        for (NSDictionary *n in nodes) { NSString *a=n[@"accessibilityIdentifier"]; if(a.length) counts[a]=@([(NSNumber *)counts[a] integerValue]+1); }
        for (NSMutableDictionary *n in nodes) { NSString *a=n[@"accessibilityIdentifier"]; if(a.length) n[@"accessibilityIdentifierUniqueInCapture"]=@([(NSNumber *)counts[a] integerValue]==1); }
        NSMutableDictionary *capture=[@{ @"id":@"__CAPTURE_ID__", @"timestamp":@"__TIMESTAMP__", @"provider":@"lldb-public-uikit", @"coherence":@"main-thread-expression-while-process-stopped; model-layer-state; screenshot-not-atomic", @"truncated":@(nodeLimit||depthLimit||constraintLimit), @"nodeLimitReached":@(nodeLimit), @"depthLimitReached":@(depthLimit), @"constraintLimitReached":@(constraintLimit), @"byteLimitReached":@NO, @"limits":@{ @"maxNodes":@(maxNodes), @"maxDepth":@(maxDepth), @"maxBytes":@(maxBytes), @"constraintsPerList":@128 }, @"windows":windowInfo, @"limitations":@[ @"No logical SwiftUI tree or source provenance", @"No independent CALayer or UIViewController graph", @"No private compositor facts or Xcode issue engine", @"Text, accessibility labels and values intentionally omitted; secure fields redacted", @"Getter evaluation may run custom app code; no layout forcing or hit testing performed", @"Occlusion and ancestor clipping are not established", @"Constraint references may point outside the captured view set", @"Pointer identifiers are ephemeral; uniqueness is capture-local", @"Raw enum values follow the installed SDK; nonfinite numeric values are null" ] } mutableCopy];
        NSMutableDictionary *root=[@{ @"schemaVersion":@"ios-ui-evidence/v1", @"capture":capture, @"target":@{ @"bundleId":[NSBundle mainBundle].bundleIdentifier ?: @"", @"pid":@([NSProcessInfo processInfo].processIdentifier), @"processName":[NSProcessInfo processInfo].processName ?: @"", @"osVersion":[NSProcessInfo processInfo].operatingSystemVersionString ?: @"" }, @"nodes":nodes } mutableCopy];
        NSError *error=nil; NSData *data=[NSJSONSerialization dataWithJSONObject:root options:0 error:&error];
        NSUInteger removed=0;
        while (data.length>=maxBytes && nodes.count) {
          NSUInteger removeCount=MAX((NSUInteger)1,nodes.count/2); [nodes removeObjectsInRange:NSMakeRange(nodes.count-removeCount,removeCount)]; removed+=removeCount;
          capture[@"truncated"]=@YES; capture[@"byteLimitReached"]=@YES; capture[@"nodesRemovedForByteLimit"]=@(removed);
          data=[NSJSONSerialization dataWithJSONObject:root options:0 error:&error];
        }
        if(data && data.length<maxBytes) { result=(char *)malloc(data.length+1); if(result) { memcpy(result,data.bytes,data.length); result[data.length]='\0'; } }
      }
    }
    (unsigned long long)result;
})'''


def expression(max_nodes=2000, max_depth=40, max_bytes=16 * 1024 * 1024,
               capture_id=None, timestamp=None):
    # Autoreleased factories work in both ARC and non-ARC debugger contexts.
    source = CAPTURE_EXPRESSION.replace("[@{", "[NSMutableDictionary dictionaryWithDictionary:@{")
    source = source.replace("} mutableCopy]", "}]")
    source = source.replace('@"ancestorAlpha":num(effectiveAlpha)', '@"ancestorAlpha":@(effectiveAlpha)')
    return (source.replace("__MAX_NODES__", str(max_nodes))
            .replace("__MAX_DEPTH__", str(max_depth))
            .replace("__MAX_BYTES__", str(max_bytes))
            .replace("__CAPTURE_ID__", capture_id or str(uuid.uuid4()))
            .replace("__TIMESTAMP__", timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()))


def compiled_probe_source():
    """Normal SDK compilation avoids LLDB's framework scratch-AST imports."""
    body = expression("maxNodes", "maxDepth", "maxBytes", "PROBE_CAPTURE_ID", "PROBE_TIMESTAMP")
    body = body.replace('@"PROBE_CAPTURE_ID"', '[NSString stringWithUTF8String:captureID]')
    body = body.replace('@"PROBE_TIMESTAMP"', '[NSString stringWithUTF8String:timestamp]')
    # The expression's local limit declarations must use distinct parameter names.
    body = body.replace("NSInteger maxNodes = maxNodes, maxDepth = maxDepth;",
                        "NSInteger maxNodes = requestedMaxNodes, maxDepth = requestedMaxDepth;")
    body = body.replace("NSUInteger maxBytes = maxBytes;", "NSUInteger maxBytes = requestedMaxBytes;")
    return (PREFIX + '\nextern "C" __attribute__((visibility("default")))\n'
            'unsigned long long PuppetUICapture(int requestedMaxNodes, int requestedMaxDepth, '
            'unsigned long long requestedMaxBytes, const char *captureID, const char *timestamp) {\n'
            'if (!captureID || !timestamp || requestedMaxNodes < 1 || requestedMaxNodes > 10000 || '
            'requestedMaxDepth < 0 || requestedMaxDepth > 100 || requestedMaxBytes < 65536 || '
            'requestedMaxBytes > 33554432) return 0;\nreturn ' + body + ';\n}\n'
            'extern "C" __attribute__((visibility("default"))) int PuppetUIIsMainThread(void) '
            '{ return [NSThread isMainThread] ? 1 : 0; }\n'
            'extern "C" __attribute__((visibility("default"))) int PuppetUIFree(unsigned long long address) '
            '{ free((void *)address); return 1; }\n')


def _probe_symbol(module, name, target):
    symbol = module.FindSymbol(name, lldb.eSymbolTypeCode)
    address = symbol.GetStartAddress().GetLoadAddress(target) if symbol.IsValid() else lldb.LLDB_INVALID_ADDRESS
    if address == lldb.LLDB_INVALID_ADDRESS:
        raise ValueError("compiled probe is missing exported symbol " + name)
    return address


def _options(timeout_seconds):
    opts = lldb.SBExpressionOptions()
    opts.SetLanguage(lldb.eLanguageTypeObjC_plus_plus)
    opts.SetTimeoutInMicroSeconds(int(timeout_seconds * 1_000_000))
    opts.SetTryAllThreads(False)
    opts.SetStopOthers(True)
    opts.SetUnwindOnError(True)
    opts.SetIgnoreBreakpoints(True)
    return opts


def capture(debugger, command, exe_ctx, result, internal_dict):
    """Capture public UIKit model state; ui_capture --help lists bounded options."""
    parser = argparse.ArgumentParser(prog="ui_capture", exit_on_error=False)
    parser.add_argument("output")
    parser.add_argument("--max-nodes", type=int, default=2000)
    parser.add_argument("--max-depth", type=int, default=40)
    parser.add_argument("--max-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--compiled-probe", help="absolute path to an explicitly built iOS Simulator probe dylib")
    try:
        args = parser.parse_args(shlex.split(command))
        if not os.path.isabs(args.output):
            raise ValueError("output must be an absolute host path")
        if os.path.lexists(args.output):
            raise ValueError("output already exists; choose a new evidence file")
        if not 1 <= args.max_nodes <= 10000 or not 0 <= args.max_depth <= 100:
            raise ValueError("max-nodes must be 1..10000; max-depth must be 0..100")
        if not 65536 <= args.max_bytes <= 32 * 1024 * 1024 or not 1 <= args.timeout <= 60:
            raise ValueError("max-bytes must be 65536..33554432; timeout must be 1..60 seconds")
        if not os.path.isdir(os.path.dirname(args.output)):
            raise ValueError("output parent directory must already exist")
        process, frame = exe_ctx.GetProcess(), exe_ctx.GetFrame()
        if not process.IsValid() or process.GetState() != lldb.eStateStopped or not frame.IsValid():
            raise ValueError("a stopped target and selected main-thread frame are required; this command does not attach or resume")
        opts = _options(args.timeout)
        address, image_handle, release_address, probe_module = 0, None, None, None
        data = None
        cleanup = {"targetBuffer": "not-allocated", "probeImage": "not-loaded"}
        execution_mode = "lldb-expression"
        try:
            if args.compiled_probe:
                target = process.GetTarget()
                triple = target.GetTriple() or ""
                if "-ios" not in triple or "-simulator" not in triple:
                    raise ValueError("compiled-probe capture is iOS Simulator only; target triple is " + triple)
                if not os.path.isabs(args.compiled_probe) or not os.path.isfile(args.compiled_probe):
                    raise ValueError("compiled-probe must be an existing absolute dylib path")
                probe_path = os.path.realpath(args.compiled_probe)
                # LLDB's LoadImage wrapper can fail even when an ordinary C call
                # succeeds. Keep this bridge primitive and under our timeout.
                opts.SetLanguage(lldb.eLanguageTypeC)
                loaded = frame.EvaluateExpression(
                    '(unsigned long long)((void *(*)(const char *, int))dlopen)(%s, 2)' %
                    json.dumps(probe_path, ensure_ascii=True), opts)
                if loaded.GetError().Fail():
                    raise ValueError("could not execute compiled-probe dlopen: " + str(loaded.GetError()) +
                                     "; loader may have partially executed; inspect debugger state before retrying")
                image_handle = loaded.GetValueAsUnsigned(0)
                if not image_handle:
                    image_handle = None
                    raise ValueError("compiled-probe dlopen returned null; inspect dlerror() in this stopped thread")
                cleanup["probeImage"] = "loaded"
                probe_module = target.FindModule(lldb.SBFileSpec(probe_path))
                if not probe_module.IsValid():
                    raise ValueError("loaded compiled probe could not be resolved as an LLDB module")
                main_address = _probe_symbol(probe_module, "PuppetUIIsMainThread", target)
                capture_address = _probe_symbol(probe_module, "PuppetUICapture", target)
                release_address = _probe_symbol(probe_module, "PuppetUIFree", target)
                main_source = "((int (*)(void))0x%x)()" % main_address
                capture_id = str(uuid.uuid4())
                timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
                capture_source = ('((unsigned long long (*)(int,int,unsigned long long,const char *,const char *))0x%x)'
                                  '(%d,%d,%dULL,"%s","%s")' %
                                  (capture_address, args.max_nodes, args.max_depth, args.max_bytes, capture_id, timestamp))
                execution_mode = "compiled-simulator-probe"
            else:
                main_source = "(BOOL)[NSThread isMainThread]"
                capture_source = expression(args.max_nodes, args.max_depth, args.max_bytes)
            main = frame.EvaluateExpression(main_source, opts)
            if main.GetError().Fail():
                raise ValueError("main-thread check failed: " + str(main.GetError()) + "; for expression mode verify target.sdk-path and persistently import UIKit, QuartzCore, and Darwin; see references/lldb-capture.md")
            if main.GetValueAsUnsigned() != 1:
                raise ValueError("selected frame is not on the main thread; inspect thread list, select the main thread and a valid frame, then retry")
            value = frame.EvaluateExpression(capture_source, opts)
            if value.GetError().Fail():
                raise ValueError("capture expression failed: " + str(value.GetError()) + "; process remains stopped; inspect debugger state before continuing")
            address = value.GetValueAsUnsigned(0)
            if not address:
                raise ValueError("capture returned no buffer (allocation, JSON serialization, size, or thread-state failure); try smaller node/depth limits")
            cleanup["targetBuffer"] = "allocated"
            error = lldb.SBError()
            raw = process.ReadCStringFromMemory(address, args.max_bytes, error)
            if error.Fail() or raw is None:
                raise ValueError("could not read capture buffer: " + str(error))
            if len(raw.encode("utf-8")) >= args.max_bytes:
                raise ValueError("capture reached host byte limit; refusing potentially incomplete JSON")
            data = json.loads(raw)
            if data.get("schemaVersion") != "ios-ui-evidence/v1" or not isinstance(data.get("nodes"), list):
                raise ValueError("capture failed schema shape validation")
            data["capture"]["hostDebugger"] = "LLDB " + debugger.GetVersionString()
            data["capture"]["executionMode"] = execution_mode
            if args.compiled_probe:
                data["capture"]["provider"] = "lldb-public-uikit-compiled-probe"
                data["capture"]["compiledProbe"] = probe_path
        finally:
            if address:
                if process.GetState() == lldb.eStateStopped:
                    free_source = ("((int (*)(unsigned long long))0x%x)(%dULL)" % (release_address, address)
                                   if release_address else "(free((void *)0x%x), 1)" % address)
                    released = frame.EvaluateExpression(free_source, opts)
                    free_failed = released.GetError().Fail() or released.GetValueAsSigned(0) != 1
                    cleanup["targetBuffer"] = "free-failed" if free_failed else "freed"
                    if free_failed:
                        result.AppendWarning("Target buffer at 0x%x could not be freed: %s. Inspect state; do not retry blindly." % (address, released.GetError()))
                else:
                    cleanup["targetBuffer"] = "not-freed-process-not-stopped"
                    result.AppendWarning("Target buffer at 0x%x remains allocated because the process is not stopped." % address)
            if image_handle is not None:
                on_stack = False
                stack_incomplete = False
                inspected_threads = 0
                if probe_module is not None and probe_module.IsValid():
                    for thread in process:
                        inspected_threads += 1
                        frame_count = thread.GetNumFrames()
                        if frame_count == 0 or frame_count > 200:
                            stack_incomplete = True
                        for index in range(min(frame_count, 200)):
                            stack_frame = thread.GetFrameAtIndex(index)
                            if not stack_frame.IsValid():
                                stack_incomplete = True
                            if stack_frame.GetModule() == probe_module:
                                on_stack = True
                                break
                else:
                    stack_incomplete = True
                if inspected_threads == 0:
                    stack_incomplete = True
                if process.GetState() != lldb.eStateStopped or on_stack or stack_incomplete:
                    cleanup["probeImage"] = "not-unloaded-unsafe-debugger-state"
                    result.AppendWarning("Compiled probe handle 0x%x remains loaded because execution is not safely outside the probe or stack inspection was incomplete; inspect debugger state." % image_handle)
                else:
                    unloaded = frame.EvaluateExpression(
                        '(int)((int (*)(void *))dlclose)((void *)0x%x)' % image_handle, opts)
                    close_failed = unloaded.GetError().Fail() or unloaded.GetValueAsSigned(-1) != 0
                    cleanup["probeImage"] = "dlclose-failed" if close_failed else "dlclose-succeeded"
                    if close_failed:
                        result.AppendWarning("Compiled probe handle 0x%x could not be closed: %s" % (image_handle, unloaded.GetError()))
            if data is not None:
                data["capture"]["cleanup"] = cleanup
        # Publish after cleanup so the evidence includes actual cleanup outcomes.
        output = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(output) > args.max_bytes:
            raise ValueError("capture plus host metadata exceeds max-bytes")
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(output)
        with open(args.output, "r", encoding="utf-8") as handle:
            json.load(handle)
        result.AppendMessage("Captured %d native views to %s; truncated=%s; mode=%s; cleanup=%s. Target remains stopped." % (len(data["nodes"]), args.output, data["capture"]["truncated"], execution_mode, json.dumps(cleanup, sort_keys=True)))
    except (ValueError, OSError, argparse.ArgumentError) as exc:
        result.SetError(str(exc))
    except SystemExit as exc:
        if exc.code:
            result.SetError("invalid arguments; see ui_capture --help")


def __lldb_init_module(debugger, internal_dict):
    debugger.HandleCommand("command script add --overwrite -f %s.capture ui_capture" % __name__)
    print("ui_capture installed. Capture requires a stopped, selected main-thread frame; see ui_capture --help.")
