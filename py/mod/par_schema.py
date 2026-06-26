"""
par_schema — the single TD-parameter <-> rship-schema reflector.

ONE place that maps a TD ParGroup to (a) an rship WELL-KNOWN SchemaRef, (b) a plain inline
JSON Schema, and (c) reads/writes the parameter value in the canonical shape the schema
implies. The comp-engine cap reflection, the Python target API's par-backed properties, and
the tag-based reflection wrappers all delegate here so they agree on types, value shapes,
and write semantics.

Well-known schema catalog (authoritative — server-side libs/entities/shared-schemas
well_known.rs; a CLOSED set):
  Bool, Scalar, Scalar01, Int, String, BlendMode, Color{r,g,b,a}, Vec3{x,y,z},
  Mask, Texture, Volume3D, Signal, EnumOf{variants:[str]}.
There is NO Vec2/Vec4/Pulse/Null/Any. So XY/XYZW/UV/UVW/WH have no canonical well-known
type (inline-only). A no-payload action (Pulse/Momentary) carries an empty schema {}.
EnumOf carries a bare string list; value == label (TD menuLabels are not representable).
"""
import td


def well_known(type_name, **extra):
    """An rship WellKnown SchemaRef: {"kind":"WellKnown","value":{"type":..., **extra}}.
    Internally tagged on "type" in PascalCase (the casing trap)."""
    value = {"type": type_name}
    value.update(extra)
    return {"kind": "WellKnown", "value": value}


def custom(json_schema):
    """An rship Custom SchemaRef wrapping an inline JSON Schema: {"kind":"Custom","value":...}.
    Lossless but GENERIC — the server renders per-field editors (an {r,g,b,a} object collapses
    to a Color widget, but there's no bespoke typed widget; that's the WellKnown path). Cap
    values stay opaque (schema is for typing/rendering only, no validation). Prefer WellKnown,
    then DECOMPOSE; reach for Custom only when a par shape can't decompose cleanly."""
    return {"kind": "Custom", "value": json_schema}


# TD par style -> well-known type name (None => no canonical well-known; use inline_schema).
# Corrected against the authoritative catalog: RGB is a Color (alpha defaulted to 1), and
# the Vec family has ONLY Vec3 — XY/XYZW/UV/UVW/WH have no well-known type.
_WELL_KNOWN = {
    "Float": "Scalar", "Int": "Int",
    "Toggle": "Bool",
    "Str": "String", "StrMenu": "String", "File": "String", "Folder": "String",
    "RGB": "Color", "RGBA": "Color",
    "XYZ": "Vec3",
}

# TD par style -> ordered component keys (multi-component value shapes).
_COMPONENTS = {
    "RGB": ["r", "g", "b"], "RGBA": ["r", "g", "b", "a"],
    "XYZ": ["x", "y", "z"], "XY": ["x", "y"], "XYZW": ["x", "y", "z", "w"],
    "UV": ["u", "v"], "UVW": ["u", "v", "w"], "WH": ["w", "h"],
}

_SCALAR_INLINE = {
    "Float": {"type": "number"}, "Int": {"type": "integer"}, "Toggle": {"type": "boolean"},
    "Str": {"type": "string"}, "StrMenu": {"type": "string"},
    "File": {"type": "string"}, "Folder": {"type": "string"},
}


def is_trigger(par_group) -> bool:
    """Pulse/Momentary is a FIRE/exec input, not a value — it has nothing to read or write.
    Comp-engine routes it as a TriggerDef (fire button); the property API exposes it as a
    no-payload ACTION (NOT a property — a property needs a value). Callers branch on this."""
    return par_group.style in ("Pulse", "Momentary")


def schema_ref(par_group):
    """The rship WELL-KNOWN value SchemaRef for this par, or None when it has no well-known
    VALUE type. None for: a TRIGGER (Pulse/Momentary — no value at all; route it as a
    trigger/action), and the no-well-known multi-component styles (XY/4-comp XYZW/UV/UVW/WH —
    caller decomposes or inlines). Menu -> EnumOf(menu values)."""
    if is_trigger(par_group):
        return None
    style = par_group.style
    if style == "Menu":
        return well_known("EnumOf", variants=list(par_group[0].menuNames))
    # The vec family maps by ACTUAL component count: TD lets an XYZ/XYZW group hold 3 members
    # (x,y,z), which IS a Vec3 regardless of the style name carrying a 'w'.
    if style in ("XYZ", "XYZW") and len(par_group) == 3:
        return well_known("Vec3")
    wk = _WELL_KNOWN.get(style)
    return well_known(wk) if wk else None


def inline_schema(par_group):
    """A plain JSON Schema for this par — full coverage, including the no-well-known styles.
    Matches the canonical value shape from read()."""
    style = par_group.style
    if is_trigger(par_group):
        return {}                                       # no payload
    if style == "Menu":
        return {"type": "string", "enum": list(par_group[0].menuNames)}
    if style in _SCALAR_INLINE:
        return dict(_SCALAR_INLINE[style])
    if style in ("RGB", "RGBA"):
        keys = ["r", "g", "b", "a"]                     # Color shape always carries alpha
    else:
        keys = _COMPONENTS.get(style)
        if keys is not None:
            keys = keys[:len(par_group)]                # honor actual component count (XYZW-size-3 -> x,y,z)
    if keys is None:                                    # unknown -> permissive
        return {}
    return {"type": "object", "properties": {k: {"type": "number"} for k in keys}}


def custom_schema_ref(par_group):
    """A Custom (inline-JSON) SchemaRef for this par — the LOSSLESS generic fallback when no
    well-known type fits and decomposition isn't desired. None for a trigger (no value)."""
    if is_trigger(par_group):
        return None
    return custom(inline_schema(par_group))


def _read(par_group, getter):
    """Shared shaper for read()/read_default(): pull each member's value via `getter`
    (.eval() for current, .default for the par default) into the canonical schema shape."""
    style = par_group.style
    if is_trigger(par_group):
        return None
    keys = _COMPONENTS.get(style)
    if keys is None:                                    # single-valued
        v = getter(par_group[0])
        return bool(v) if style == "Toggle" else v
    vals = {k: float(getter(p)) for k, p in zip(keys, par_group)}
    if style == "RGB":                                  # Color shape carries alpha
        vals["a"] = 1.0
    return vals


def read(par_group):
    """Current value in the canonical shape the schema implies: bool/number/integer/string
    for single pars (Menu -> the menu value string); {r,g,b,a} for Color (RGB defaults a=1);
    {x,y,z}/{x,y}/{x,y,z,w}/{u,v}/... for the vec family; None for a trigger."""
    return _read(par_group, lambda p: p.eval())


def read_default(par_group):
    """The par's DEFAULT value in the SAME canonical shape as read() (each member's .default
    rather than its current value). Used to seed a comp-engine cap's `default` so the server
    populates a newly-placed comp-element instance with the TD-authored defaults instead of
    null. None for a trigger (no value)."""
    return _read(par_group, lambda p: p.default)


def write(par_group, value) -> bool:
    """ParMode-SAFE write. Returns True if applied; False (no-op) if any member par is NOT
    in CONSTANT mode — a .val write to an expression/export/bind-driven par is silently
    ignored by TD, so we refuse rather than report a phantom success. Trigger -> pulse."""
    members = list(par_group)
    for p in members:
        if getattr(p, "mode", None) != ParMode.CONSTANT:
            return False
    if is_trigger(par_group):
        members[0].pulse()
        return True
    if value is None:                                   # no desired value (cap unset, e.g. a freshly
        return False                                    # placed instance) -> no-op; writing None to a
                                                        # numeric par throws the cast (matches _set).
    keys = _COMPONENTS.get(par_group.style)
    if keys is None:
        members[0].val = value
        return True
    for k, p in zip(keys, members):                     # multi-component: value is a dict
        if isinstance(value, dict) and k in value:
            p.val = value[k]
    return True
