# SPDX-License-Identifier: GPL-2.0-or-later
#
# BlendEngine data model.

import bpy
from bpy.types import PropertyGroup


TARGET_PLATFORM_ITEMS = (
    ("WINDOWS", "Windows", "Prepare a Windows desktop build profile"),
    ("LINUX", "Linux", "Prepare a Linux desktop build profile"),
    ("MACOS", "macOS", "Prepare a macOS desktop build profile"),
    ("IOS", "iOS", "Prepare an iPhone and iPad build profile"),
    ("ANDROID", "Android", "Prepare an Android phone, tablet, and TV build profile"),
    ("WEB", "Web", "Prepare a browser-ready Web build profile"),
)

GAME_DIMENSION_ITEMS = (
    ("THREE_D", "3D Game", "Create a 3D game with player, camera, physics, and world streaming"),
    ("TWO_D", "2D Game", "Create a 2D game with orthographic camera and simple controls"),
)

EASY_GAME_TEMPLATE_ITEMS = (
    ("THREE_D_ADVENTURE", "3D Adventure", "One-click 3D starter game"),
    ("CYBERPUNK_SHOOTER", "Cyberpunk Zombie Shooter", "Import provided models and create a first-person gun game"),
    ("TWO_D_PLATFORMER", "2D Platformer", "One-click 2D side-view starter game"),
    ("MOBILE_3D", "Mobile 3D", "One-click touch-friendly 3D starter game"),
)

QUALITY_ITEMS = (
    ("LOW", "Low", "Simple effects and lower resolution defaults"),
    ("MEDIUM", "Medium", "Balanced default quality"),
    ("HIGH", "High", "Higher quality defaults"),
    ("CINEMATIC", "Cinematic", "Film-style preview defaults"),
)

COMPONENT_TYPE_ITEMS = (
    ("TRANSFORM", "Transform", "Use the Blender object transform as gameplay transform"),
    ("MESH_RENDERER", "Mesh Renderer", "Treat this object as a visible gameplay mesh"),
    ("COLLIDER", "Collider", "Gameplay collision shape"),
    ("RIGIDBODY", "Rigidbody", "Physics body driven by Blender rigid body settings"),
    ("PLAYER_CONTROLLER", "Player Controller", "Configurable player movement component"),
    ("NPC_CONTROLLER", "NPC Controller", "Template-driven non-player character behavior"),
    ("CAMERA_CONTROLLER", "Camera Controller", "Gameplay camera behavior"),
    ("TRIGGER_ZONE", "Trigger Zone", "Invisible gameplay trigger volume"),
    ("HEALTH", "Health", "Health and death data"),
    ("DAMAGE", "Damage", "Damage-dealing behavior"),
    ("INVENTORY", "Inventory", "Inventory owner or item storage"),
    ("DIALOGUE", "Dialogue", "Dialogue and caption data"),
    ("QUEST", "Quest", "Quest state data"),
    ("DOOR", "Door", "Openable door behavior"),
    ("PICKUP_ITEM", "Pickup Item", "Collectable gameplay item"),
    ("WEAPON", "Weapon", "Weapon behavior"),
    ("UI_ELEMENT", "UI Element", "HUD or interface element"),
    ("AUDIO_SOURCE", "Audio Source", "Gameplay audio emitter"),
    ("ANIMATION_CONTROLLER", "Animation Controller", "No-code animation state machine"),
    ("STATIC_OBJECT", "Static Object", "Object does not move during gameplay"),
    ("DYNAMIC_OBJECT", "Dynamic Object", "Object can move or change during gameplay"),
    ("OCCLUDER", "Occluder", "Candidate for future occlusion culling"),
    ("LOD_GROUP", "LOD Group", "Object has or needs level-of-detail variants"),
    ("IMPOSTOR_CANDIDATE", "Impostor Candidate", "Candidate for a far-distance billboard or proxy"),
    ("BAKED_LIGHTING_CANDIDATE", "Baked Lighting Candidate", "Lighting should be baked when possible"),
    ("COLLIDER_SIMPLIFICATION", "Collider Simplification", "Use a simpler gameplay collision shape"),
    ("DISABLE_WHEN_FAR", "Disable When Far", "Can be hidden or disabled at long distance"),
    ("ANIMATION_CULLING", "Animation Culling", "Can update animation less often when far away"),
    ("PHYSICS_SLEEP", "Physics Sleep", "Can sleep physics when not active"),
    ("MERGE_CANDIDATE", "Merge Candidate", "Can be merged with nearby static objects later"),
    ("INSTANCING_CANDIDATE", "Instancing Candidate", "Can use instancing when repeated"),
)

CONTROLLER_TYPE_ITEMS = (
    ("FIRST_PERSON", "First Person Controller", "Walk from a first-person camera"),
    ("THIRD_PERSON", "Third Person Controller", "Follow a character from behind"),
    ("TOP_DOWN", "Top Down Controller", "Move from a top-down camera"),
    ("SIDE_SCROLLER", "Side Scroller Controller", "Move mostly left and right"),
    ("VEHICLE", "Vehicle Controller", "Vehicle-style steering"),
    ("FLYING", "Flying Controller", "Free flying movement"),
    ("CUSTOM", "Custom Controller", "Use custom scripting or runtime hooks"),
)

AI_TEMPLATE_ITEMS = (
    ("IDLE", "Idle", "Stay in place"),
    ("PATROL", "Patrol", "Move around a patrol area"),
    ("FOLLOW_PLAYER", "Follow Player", "Follow the selected player"),
    ("FLEE", "Flee", "Move away from danger"),
    ("ATTACK", "Attack", "Attack a target when close"),
    ("GUARD_AREA", "Guard Area", "Protect a location"),
    ("TALK", "Talk", "Start a dialogue interaction"),
    ("QUEST_GIVER", "Quest Giver", "Offer and complete quests"),
    ("SHOPKEEPER", "Shopkeeper", "Open a shop interaction"),
    ("ENEMY_BOSS", "Enemy Boss", "Use boss-style enemy settings"),
    ("COMPANION", "Companion", "Follow and assist the player"),
)

EVENT_TYPE_ITEMS = (
    ("ON_START", "On Start", "Run when the scene starts"),
    ("ON_UPDATE", "On Update", "Run every gameplay update"),
    ("ON_KEY_PRESS", "On Key Press", "Run when a key is pressed"),
    ("ON_CLICK_OBJECT", "On Click Object", "Run when this object is clicked"),
    ("ON_COLLISION", "On Collision", "Run when colliding with another object"),
    ("ON_ENTER_TRIGGER", "On Enter Trigger", "Run when something enters a trigger"),
    ("ON_TIMER", "On Timer", "Run after a timer"),
    ("ON_HEALTH_CHANGED", "On Health Changed", "Run when health changes"),
    ("ON_QUEST_COMPLETE", "On Quest Complete", "Run when a quest completes"),
    ("CUSTOM_EVENT", "Custom Event", "Run from a named gameplay event"),
)

CONDITION_TYPE_ITEMS = (
    ("ALWAYS", "Always", "No condition"),
    ("VARIABLE_COMPARE", "Variable Compare", "Compare a game variable"),
    ("HEALTH_COMPARE", "Health Compare", "Compare health"),
    ("IS_GROUNDED", "Is Grounded", "Check if the object is grounded"),
    ("KEY_HELD", "Key Held", "Check if a key is held"),
    ("TAG_MATCH", "Tag Match", "Check another object's tag"),
    ("TIMER_FINISHED", "Timer Finished", "Check if a timer has finished"),
    ("EVENT_TRIGGERED", "Event Triggered", "Check if an event was triggered"),
)

COMPARE_ITEMS = (
    ("EQUAL", "=", "Equal to"),
    ("NOT_EQUAL", "!=", "Not equal to"),
    ("LESS", "<", "Less than"),
    ("LESS_EQUAL", "<=", "Less than or equal to"),
    ("GREATER", ">", "Greater than"),
    ("GREATER_EQUAL", ">=", "Greater than or equal to"),
)

ACTION_TYPE_ITEMS = (
    ("PLAY_ANIMATION", "Play Animation", "Play an animation action or state"),
    ("MOVE_FORWARD", "Move Forward", "Move using the player controller forward direction"),
    ("MOVE_OBJECT", "Move Object", "Move a target object"),
    ("ROTATE_OBJECT", "Rotate Object", "Rotate a target object"),
    ("SET_VARIABLE", "Set Variable", "Set a game variable"),
    ("CHANGE_HEALTH", "Change Health", "Add or remove health"),
    ("OPEN_DOOR", "Open Door", "Open a configured door"),
    ("START_CUTSCENE", "Start Cutscene", "Start a cutscene sequence"),
    ("SPAWN_OBJECT", "Spawn Object", "Spawn an object or prefab later"),
    ("LOAD_SCENE", "Load Scene", "Load another scene later"),
    ("GAME_OVER", "Game Over", "Trigger game over state"),
    ("SHOW_LOG", "Show Log", "Write a readable message to the BlendEngine log"),
    ("CUSTOM_SCRIPT", "Custom Script", "Call an optional Python script later"),
)

INPUT_ACTION_ITEMS = (
    ("MOVE_FORWARD", "Move Forward", "Move forward"),
    ("MOVE_BACKWARD", "Move Backward", "Move backward"),
    ("MOVE_LEFT", "Move Left", "Move left"),
    ("MOVE_RIGHT", "Move Right", "Move right"),
    ("JUMP", "Jump", "Jump"),
    ("SPRINT", "Sprint", "Sprint"),
    ("CROUCH", "Crouch", "Crouch"),
    ("INTERACT", "Interact", "Interact with objects"),
    ("ATTACK", "Attack", "Attack"),
    ("AIM", "Aim", "Aim"),
    ("PAUSE", "Pause", "Pause the game"),
    ("INVENTORY", "Inventory", "Open inventory"),
    ("CUSTOM", "Custom Action", "Custom gameplay input action"),
)

ANIMATION_STATE_ITEMS = (
    ("IDLE", "Idle", "Idle animation state"),
    ("WALK", "Walk", "Walk animation state"),
    ("RUN", "Run", "Run animation state"),
    ("JUMP", "Jump", "Jump animation state"),
    ("FALL", "Fall", "Fall animation state"),
    ("ATTACK", "Attack", "Attack animation state"),
    ("HIT", "Hit", "Hit reaction animation state"),
    ("DEATH", "Death", "Death animation state"),
    ("CUSTOM", "Custom", "Custom animation state"),
)

TRANSITION_TRIGGER_ITEMS = (
    ("SPEED_GREATER", "Speed > Value", "Switch when speed is greater than a value"),
    ("SPEED_LESS", "Speed < Value", "Switch when speed is less than a value"),
    ("IS_GROUNDED", "IsGrounded True", "Switch when grounded"),
    ("IS_NOT_GROUNDED", "IsGrounded False", "Switch when not grounded"),
    ("KEY_PRESSED", "Key Pressed", "Switch when a key is pressed"),
    ("HEALTH_LESS_EQUAL", "Health <= Value", "Switch when health is low"),
    ("EVENT_TRIGGERED", "Event Triggered", "Switch when an event is triggered"),
    ("TIMER_FINISHED", "Timer Finished", "Switch when a timer finishes"),
)

OPTIMIZATION_PRESET_ITEMS = (
    ("ULTRA_LOW", "Ultra Low", "Maximum speed for very weak computers"),
    ("LOW", "Low", "Fast settings for older computers"),
    ("BALANCED", "Balanced", "Good default for lightweight games"),
    ("HIGH", "High", "Better visuals on stronger computers"),
    ("CINEMATIC", "Cinematic", "Highest visuals for screenshots and strong computers"),
    ("CUSTOM", "Custom", "Manual optimization settings"),
)

TEXTURE_QUALITY_ITEMS = (
    ("LOW", "Low", "Small textures, fastest memory use"),
    ("MEDIUM", "Medium", "Balanced texture quality"),
    ("HIGH", "High", "High texture detail"),
    ("ULTRA", "Ultra", "Very high texture detail"),
)

SHADOW_QUALITY_ITEMS = (
    ("OFF", "Off", "No real-time shadows"),
    ("LOW", "Low", "Simple low-cost shadows"),
    ("MEDIUM", "Medium", "Balanced shadows"),
    ("HIGH", "High", "Sharper shadows"),
    ("ULTRA", "Ultra", "Very high shadow quality"),
)

AA_LEVEL_ITEMS = (
    ("OFF", "Off", "No anti-aliasing"),
    ("FXAA", "FXAA", "Fast anti-aliasing"),
    ("TAA_2X", "TAA 2x", "Balanced temporal anti-aliasing"),
    ("TAA_4X", "TAA 4x", "Higher quality temporal anti-aliasing"),
    ("TAA_8X", "TAA 8x", "Expensive temporal anti-aliasing"),
)

OPTIMIZATION_QUALITY_ITEMS = (
    ("OFF", "Off", "Disabled"),
    ("LOW", "Low", "Fastest setting"),
    ("MEDIUM", "Medium", "Balanced setting"),
    ("HIGH", "High", "High quality setting"),
    ("ULTRA", "Ultra", "Most expensive setting"),
)

REPORT_SEVERITY_ITEMS = (
    ("GOOD", "Good", "The estimate is inside the selected budget"),
    ("WARNING", "Warning", "This may slow the game on weaker computers"),
    ("CRITICAL", "Critical", "This is likely too expensive for the selected budget"),
    ("SUGGESTED_FIX", "Suggested Fix", "A beginner-friendly optimization suggestion"),
)

EDITOR_BOTTOM_TAB_ITEMS = (
    ("ASSETS", "Assets", "Asset and content browser workflow"),
    ("CONSOLE", "Console", "Runtime logs, errors, and warnings"),
    ("ANIMATION", "Animation", "Timeline, states, and cutscene workflow"),
    ("PROFILER", "Profiler", "Frame time, memory, and performance workflow"),
)

MULTIPLAYER_MODE_ITEMS = (
    ("SINGLE_PLAYER", "Single Player", "No networking"),
    ("LOCAL", "Local", "Local split-screen or same-machine testing"),
    ("LAN", "LAN", "Local network multiplayer"),
    ("ONLINE_SERVER", "Online Server", "Online client/server profile"),
    ("DEDICATED_SERVER", "Dedicated Server", "Headless authoritative server profile"),
)


class BE_GameEvent(PropertyGroup):
    name: bpy.props.StringProperty(
        name="Name",
        default="On Start",
        description="Readable name for this event",
    )
    event_type: bpy.props.EnumProperty(
        name="Event",
        items=EVENT_TYPE_ITEMS,
        default="ON_START",
        description="When this behavior should run",
    )
    key: bpy.props.StringProperty(
        name="Key",
        default="SPACE",
        description="Keyboard key used by key events",
    )
    tag: bpy.props.StringProperty(
        name="Tag",
        default="",
        description="Collision or trigger tag filter",
    )
    timer_seconds: bpy.props.FloatProperty(
        name="Timer",
        default=1.0,
        min=0.0,
        description="Seconds before a timer event fires",
    )
    custom_event: bpy.props.StringProperty(
        name="Custom Event",
        default="",
        description="Named custom event for advanced workflows",
    )


class BE_GameCondition(PropertyGroup):
    name: bpy.props.StringProperty(
        name="Name",
        default="Always",
        description="Readable name for this condition",
    )
    condition_type: bpy.props.EnumProperty(
        name="Condition",
        items=CONDITION_TYPE_ITEMS,
        default="ALWAYS",
        description="Optional requirement before actions run",
    )
    variable_name: bpy.props.StringProperty(
        name="Variable",
        default="",
        description="Game variable to compare",
    )
    compare: bpy.props.EnumProperty(
        name="Compare",
        items=COMPARE_ITEMS,
        default="EQUAL",
        description="Comparison operator",
    )
    number_value: bpy.props.FloatProperty(
        name="Value",
        default=0.0,
        description="Numeric value used by this condition",
    )
    text_value: bpy.props.StringProperty(
        name="Text",
        default="",
        description="Text value used by this condition",
    )
    bool_value: bpy.props.BoolProperty(
        name="Bool",
        default=True,
        description="Boolean value used by this condition",
    )


class BE_GameAction(PropertyGroup):
    name: bpy.props.StringProperty(
        name="Name",
        default="Show Log",
        description="Readable name for this action",
    )
    action_type: bpy.props.EnumProperty(
        name="Action",
        items=ACTION_TYPE_ITEMS,
        default="SHOW_LOG",
        description="What this behavior should do",
    )
    target_object: bpy.props.PointerProperty(
        name="Target Object",
        type=bpy.types.Object,
        description="Object affected by this action",
    )
    animation: bpy.props.PointerProperty(
        name="Animation",
        type=bpy.types.Action,
        description="Animation action used by this gameplay action",
    )
    scene: bpy.props.PointerProperty(
        name="Scene",
        type=bpy.types.Scene,
        description="Scene used by load-scene style actions",
    )
    variable_name: bpy.props.StringProperty(
        name="Variable",
        default="",
        description="Game variable this action changes",
    )
    number_value: bpy.props.FloatProperty(
        name="Value",
        default=1.0,
        description="Numeric action value",
    )
    text_value: bpy.props.StringProperty(
        name="Text",
        default="Hello from BlendEngine",
        description="Text or log message used by this action",
    )
    vector_value: bpy.props.FloatVectorProperty(
        name="Vector",
        default=(0.0, 0.0, 0.0),
        subtype="TRANSLATION",
        description="Vector value used by movement actions",
    )


class BE_GameBehavior(PropertyGroup):
    name: bpy.props.StringProperty(
        name="Behavior",
        default="New Behavior",
        description="No-code gameplay behavior attached to an object",
    )
    enabled: bpy.props.BoolProperty(
        name="Enabled",
        default=True,
        description="Run this behavior during gameplay",
    )
    description: bpy.props.StringProperty(
        name="Description",
        default="",
        description="Plain-language purpose of this behavior",
    )
    events: bpy.props.CollectionProperty(type=BE_GameEvent)
    active_event_index: bpy.props.IntProperty(default=0)
    conditions: bpy.props.CollectionProperty(type=BE_GameCondition)
    active_condition_index: bpy.props.IntProperty(default=0)
    actions: bpy.props.CollectionProperty(type=BE_GameAction)
    active_action_index: bpy.props.IntProperty(default=0)


class BE_GameVariable(PropertyGroup):
    name: bpy.props.StringProperty(
        name="Name",
        default="NewVariable",
        description="Gameplay variable name",
    )
    variable_type: bpy.props.EnumProperty(
        name="Type",
        items=(
            ("BOOL", "Bool", "True or false variable"),
            ("INT", "Integer", "Whole number variable"),
            ("FLOAT", "Float", "Decimal number variable"),
            ("STRING", "String", "Text variable"),
        ),
        default="FLOAT",
        description="Kind of data stored by this variable",
    )
    bool_value: bpy.props.BoolProperty(name="Bool", default=False)
    int_value: bpy.props.IntProperty(name="Integer", default=0)
    float_value: bpy.props.FloatProperty(name="Float", default=0.0)
    string_value: bpy.props.StringProperty(name="String", default="")
    description: bpy.props.StringProperty(
        name="Description",
        default="",
        description="Plain-language description for beginners",
    )


class BE_GameObjectComponent(PropertyGroup):
    name: bpy.props.StringProperty(
        name="Name",
        default="Component",
        description="Readable component name",
    )
    component_type: bpy.props.EnumProperty(
        name="Type",
        items=COMPONENT_TYPE_ITEMS,
        default="TRANSFORM",
        description="Gameplay component type",
    )
    enabled: bpy.props.BoolProperty(
        name="Enabled",
        default=True,
        description="Enable this gameplay component",
    )
    tag: bpy.props.StringProperty(
        name="Tag",
        default="",
        description="Optional gameplay tag",
    )
    notes: bpy.props.StringProperty(
        name="Notes",
        default="",
        description="Beginner-friendly notes for this component",
    )


class BE_PlayerControllerSettings(PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Enabled",
        default=False,
        description="Use this object as a player controller",
    )
    controller_type: bpy.props.EnumProperty(
        name="Controller Type",
        items=CONTROLLER_TYPE_ITEMS,
        default="THIRD_PERSON",
        description="Movement preset for this player",
    )
    walk_speed: bpy.props.FloatProperty(name="Walk Speed", default=4.0, min=0.0)
    run_speed: bpy.props.FloatProperty(name="Run Speed", default=8.0, min=0.0)
    jump_force: bpy.props.FloatProperty(name="Jump Force", default=6.0, min=0.0)
    gravity: bpy.props.FloatProperty(name="Gravity", default=9.81, min=0.0)
    mouse_sensitivity: bpy.props.FloatProperty(name="Mouse Sensitivity", default=1.0, min=0.01)
    camera_follow: bpy.props.PointerProperty(
        name="Camera Follow",
        type=bpy.types.Object,
        description="Camera that follows this player",
    )
    rotation_smoothing: bpy.props.FloatProperty(name="Rotation Smoothing", default=8.0, min=0.0)
    acceleration: bpy.props.FloatProperty(name="Acceleration", default=20.0, min=0.0)
    deceleration: bpy.props.FloatProperty(name="Deceleration", default=24.0, min=0.0)
    ground_detection: bpy.props.BoolProperty(name="Ground Detection", default=True)
    crouch: bpy.props.BoolProperty(name="Crouch", default=False)
    sprint: bpy.props.BoolProperty(name="Sprint", default=True)
    climb: bpy.props.BoolProperty(name="Climb", default=False)
    swim: bpy.props.BoolProperty(name="Swim", default=False)
    interact_key: bpy.props.StringProperty(name="Interact Key", default="E")
    attack_key: bpy.props.StringProperty(name="Attack Key", default="LEFTMOUSE")
    idle_animation: bpy.props.PointerProperty(name="Idle", type=bpy.types.Action)
    walk_animation: bpy.props.PointerProperty(name="Walk", type=bpy.types.Action)
    run_animation: bpy.props.PointerProperty(name="Run", type=bpy.types.Action)
    jump_animation: bpy.props.PointerProperty(name="Jump", type=bpy.types.Action)
    attack_animation: bpy.props.PointerProperty(name="Attack", type=bpy.types.Action)


class BE_NPCBehaviorSettings(PropertyGroup):
    enabled: bpy.props.BoolProperty(name="Enabled", default=False)
    behavior_template: bpy.props.EnumProperty(
        name="Behavior",
        items=AI_TEMPLATE_ITEMS,
        default="IDLE",
        description="Beginner AI behavior template",
    )
    target_object: bpy.props.PointerProperty(
        name="Target",
        type=bpy.types.Object,
        description="Object this NPC watches, follows, attacks, or talks to",
    )
    move_speed: bpy.props.FloatProperty(name="Move Speed", default=3.0, min=0.0)
    patrol_radius: bpy.props.FloatProperty(name="Patrol Radius", default=5.0, min=0.0)
    detection_range: bpy.props.FloatProperty(name="Detection Range", default=10.0, min=0.0)
    attack_range: bpy.props.FloatProperty(name="Attack Range", default=2.0, min=0.0)
    dialogue_text: bpy.props.StringProperty(name="Dialogue", default="Hello!")
    quest_id: bpy.props.StringProperty(name="Quest ID", default="")


class BE_HealthSettings(PropertyGroup):
    enabled: bpy.props.BoolProperty(name="Enabled", default=False)
    max_health: bpy.props.FloatProperty(name="Max Health", default=100.0, min=0.0)
    current_health: bpy.props.FloatProperty(name="Current Health", default=100.0, min=0.0)
    destroy_on_death: bpy.props.BoolProperty(name="Destroy On Death", default=False)
    game_over_on_death: bpy.props.BoolProperty(name="Game Over On Death", default=False)


class BE_AnimationState(PropertyGroup):
    name: bpy.props.StringProperty(name="State", default="Idle")
    state_type: bpy.props.EnumProperty(
        name="Type",
        items=ANIMATION_STATE_ITEMS,
        default="IDLE",
    )
    animation: bpy.props.PointerProperty(name="Animation", type=bpy.types.Action)
    loop: bpy.props.BoolProperty(name="Loop", default=True)
    speed: bpy.props.FloatProperty(name="Speed", default=1.0, min=0.0)


class BE_AnimationTransition(PropertyGroup):
    name: bpy.props.StringProperty(name="Transition", default="New Transition")
    from_state: bpy.props.StringProperty(name="From", default="Idle")
    to_state: bpy.props.StringProperty(name="To", default="Walk")
    trigger: bpy.props.EnumProperty(
        name="Trigger",
        items=TRANSITION_TRIGGER_ITEMS,
        default="SPEED_GREATER",
    )
    key: bpy.props.StringProperty(name="Key", default="")
    event_name: bpy.props.StringProperty(name="Event", default="")
    threshold: bpy.props.FloatProperty(name="Value", default=0.1)


class BE_AnimationControllerSettings(PropertyGroup):
    enabled: bpy.props.BoolProperty(name="Enabled", default=False)
    default_state: bpy.props.StringProperty(name="Default State", default="Idle")
    states: bpy.props.CollectionProperty(type=BE_AnimationState)
    active_state_index: bpy.props.IntProperty(default=0)
    transitions: bpy.props.CollectionProperty(type=BE_AnimationTransition)
    active_transition_index: bpy.props.IntProperty(default=0)


class BE_ObjectOptimizationSettings(PropertyGroup):
    static_object: bpy.props.BoolProperty(
        name="Static Object",
        default=False,
        description="This object does not move during gameplay and can be optimized later",
    )
    dynamic_object: bpy.props.BoolProperty(
        name="Dynamic Object",
        default=False,
        description="This object moves or changes during gameplay",
    )
    occluder: bpy.props.BoolProperty(
        name="Occluder",
        default=False,
        description="Candidate for future occlusion culling",
    )
    lod_group: bpy.props.BoolProperty(
        name="LOD Group",
        default=False,
        description="This object has or should have level-of-detail variants",
    )
    lod_placeholder_count: bpy.props.IntProperty(
        name="LOD Placeholders",
        default=0,
        min=0,
        description="Number of LOD placeholder markers created for this object",
    )
    impostor_candidate: bpy.props.BoolProperty(
        name="Impostor Candidate",
        default=False,
        description="Can become a cheap far-distance impostor in runtime builds",
    )
    baked_lighting_candidate: bpy.props.BoolProperty(
        name="Baked Lighting Candidate",
        default=False,
        description="Should prefer baked lighting over real-time lighting",
    )
    collider_simplification: bpy.props.BoolProperty(
        name="Collider Simplification",
        default=False,
        description="Use a simple gameplay collider instead of a complex mesh collider",
    )
    disable_when_far: bpy.props.BoolProperty(
        name="Disable When Far",
        default=False,
        description="Can be hidden or disabled when far from the player",
    )
    disable_distance: bpy.props.FloatProperty(
        name="Disable Distance",
        default=80.0,
        min=0.0,
        description="Future distance at which this object can be disabled",
    )
    animation_culling: bpy.props.BoolProperty(
        name="Animation Culling",
        default=False,
        description="Update animation less often when this object is far away",
    )
    physics_sleep: bpy.props.BoolProperty(
        name="Physics Sleep",
        default=False,
        description="Let physics sleep when the object is not active",
    )
    merge_candidate: bpy.props.BoolProperty(
        name="Merge Candidate",
        default=False,
        description="Can be merged with nearby static objects later",
    )
    instancing_candidate: bpy.props.BoolProperty(
        name="Instancing Candidate",
        default=False,
        description="Can use future GPU instancing when repeated many times",
    )
    notes: bpy.props.StringProperty(
        name="Optimization Notes",
        default="Editor-side optimization markers used by the BlendEngine runtime and build package.",
        description="Beginner-friendly optimization notes",
    )


class BE_ObjectSettings(PropertyGroup):
    is_game_object: bpy.props.BoolProperty(
        name="Game Object",
        default=False,
        description="Treat this Blender object as a BlendEngine gameplay object",
    )
    object_tag: bpy.props.StringProperty(
        name="Tag",
        default="",
        description="Gameplay tag used by triggers, collision, and behaviors",
    )
    components: bpy.props.CollectionProperty(type=BE_GameObjectComponent)
    active_component_index: bpy.props.IntProperty(default=0)
    variables: bpy.props.CollectionProperty(type=BE_GameVariable)
    active_variable_index: bpy.props.IntProperty(default=0)
    behaviors: bpy.props.CollectionProperty(type=BE_GameBehavior)
    active_behavior_index: bpy.props.IntProperty(default=0)
    player_controller: bpy.props.PointerProperty(type=BE_PlayerControllerSettings)
    npc_behavior: bpy.props.PointerProperty(type=BE_NPCBehaviorSettings)
    health: bpy.props.PointerProperty(type=BE_HealthSettings)
    animation_controller: bpy.props.PointerProperty(type=BE_AnimationControllerSettings)
    optimization: bpy.props.PointerProperty(type=BE_ObjectOptimizationSettings)


class BE_InputBinding(PropertyGroup):
    name: bpy.props.StringProperty(
        name="Name",
        default="Input Binding",
        description="Readable input binding name",
    )
    action: bpy.props.EnumProperty(
        name="Action",
        items=INPUT_ACTION_ITEMS,
        default="MOVE_FORWARD",
        description="Gameplay action this input controls",
    )
    custom_action: bpy.props.StringProperty(
        name="Custom Action",
        default="",
        description="Name used when Action is Custom",
    )
    device: bpy.props.EnumProperty(
        name="Device",
        items=(
            ("KEYBOARD", "Keyboard", "Keyboard key"),
            ("MOUSE", "Mouse", "Mouse button"),
            ("GAMEPAD", "Gamepad", "Gamepad button or axis"),
        ),
        default="KEYBOARD",
    )
    key: bpy.props.StringProperty(
        name="Key/Button",
        default="W",
        description="Keyboard, mouse, or gamepad binding",
    )
    scale: bpy.props.FloatProperty(
        name="Scale",
        default=1.0,
        description="Input scale, useful for axes",
    )


class BE_InputMap(PropertyGroup):
    bindings: bpy.props.CollectionProperty(type=BE_InputBinding)
    active_binding_index: bpy.props.IntProperty(default=0)


class BE_ProjectSettings(PropertyGroup):
    game_title: bpy.props.StringProperty(
        name="Game Title",
        default="My BlendEngine Game",
        description="Title used by build and test-run tools",
    )
    simple_mode: bpy.props.BoolProperty(
        name="Simple Mode",
        default=True,
        description="Show beginner-friendly controls before advanced settings",
    )
    game_dimension: bpy.props.EnumProperty(
        name="Game Type",
        items=GAME_DIMENSION_ITEMS,
        default="THREE_D",
        description="Choose whether this project is mainly 3D or 2D",
    )
    default_scene: bpy.props.PointerProperty(name="Default Scene", type=bpy.types.Scene)
    main_menu_scene: bpy.props.PointerProperty(name="Main Menu Scene", type=bpy.types.Scene)
    loading_screen_scene: bpy.props.PointerProperty(name="Loading Screen Scene", type=bpy.types.Scene)
    target_platform: bpy.props.EnumProperty(
        name="Target Platform",
        items=TARGET_PLATFORM_ITEMS,
        default="WINDOWS",
    )
    resolution_x: bpy.props.IntProperty(name="Width", default=1280, min=1)
    resolution_y: bpy.props.IntProperty(name="Height", default=720, min=1)
    display_mode: bpy.props.EnumProperty(
        name="Display",
        items=(
            ("WINDOWED", "Windowed", "Start in a window"),
            ("FULLSCREEN", "Fullscreen", "Start fullscreen"),
        ),
        default="WINDOWED",
    )
    quality_level: bpy.props.EnumProperty(
        name="Quality",
        items=QUALITY_ITEMS,
        default="MEDIUM",
    )
    save_system_enabled: bpy.props.BoolProperty(name="Save System", default=False)
    physics_gravity: bpy.props.FloatProperty(name="Physics Gravity", default=9.81, min=0.0)
    build_folder: bpy.props.StringProperty(
        name="Build Folder",
        subtype="DIR_PATH",
        default="//builds/BlendEngine",
    )
    show_fps: bpy.props.BoolProperty(name="Show FPS", default=True)
    show_colliders: bpy.props.BoolProperty(name="Show Colliders", default=False)
    show_navigation: bpy.props.BoolProperty(name="Show Navigation", default=False)
    show_game_variables: bpy.props.BoolProperty(name="Show Game Variables", default=False)
    show_logs: bpy.props.BoolProperty(name="Show Logs", default=True)
    debug_mode: bpy.props.BoolProperty(name="Debug Mode", default=False)
    test_running: bpy.props.BoolProperty(name="Test Running", default=False)
    test_status: bpy.props.StringProperty(name="Test Status", default="Not running")
    runtime_fps: bpy.props.FloatProperty(name="Runtime FPS", default=0.0, min=0.0)
    runtime_frame_ms: bpy.props.FloatProperty(name="Frame Time MS", default=0.0, min=0.0)
    runtime_memory_mb: bpy.props.FloatProperty(name="Runtime Memory MB", default=0.0, min=0.0)
    runtime_visible_objects: bpy.props.IntProperty(name="Visible Objects", default=0, min=0)
    runtime_draw_calls_estimated: bpy.props.IntProperty(name="Draw Calls", default=0, min=0)
    runtime_triangles_visible: bpy.props.IntProperty(name="Visible Triangles", default=0, min=0)
    runtime_texture_memory_mb: bpy.props.FloatProperty(name="Texture Memory MB", default=0.0, min=0.0)


class BE_ExportSettings(PropertyGroup):
    export_playable_project: bpy.props.BoolProperty(name="Playable Project", default=True)
    export_assets: bpy.props.BoolProperty(name="Assets", default=True)
    export_scene_package: bpy.props.BoolProperty(name="Scene Package", default=True)
    include_debug_overlay: bpy.props.BoolProperty(name="Debug Overlay", default=False)
    package_name: bpy.props.StringProperty(name="Package Name", default="BlendEngineBuild")


class BE_GameQualityProfile(PropertyGroup):
    preset: bpy.props.EnumProperty(
        name="Preset",
        items=OPTIMIZATION_PRESET_ITEMS,
        default="BALANCED",
        description="Beginner-friendly optimization preset",
    )
    name: bpy.props.StringProperty(name="Profile Name", default="Balanced")
    target_fps: bpy.props.IntProperty(name="Target FPS", default=60, min=15, max=240)
    resolution_scale: bpy.props.FloatProperty(
        name="Resolution Scale",
        default=1.0,
        min=0.25,
        max=2.0,
        description="Render at a lower or higher internal resolution",
    )
    texture_quality: bpy.props.EnumProperty(
        name="Texture Quality",
        items=TEXTURE_QUALITY_ITEMS,
        default="MEDIUM",
    )
    shadow_quality: bpy.props.EnumProperty(
        name="Shadow Quality",
        items=SHADOW_QUALITY_ITEMS,
        default="MEDIUM",
    )
    shadow_distance: bpy.props.FloatProperty(name="Shadow Distance", default=40.0, min=0.0)
    anti_aliasing: bpy.props.EnumProperty(
        name="Anti-Aliasing",
        items=AA_LEVEL_ITEMS,
        default="TAA_2X",
    )
    ambient_occlusion: bpy.props.BoolProperty(name="Ambient Occlusion", default=True)
    bloom: bpy.props.BoolProperty(name="Bloom", default=True)
    reflections: bpy.props.BoolProperty(name="Screen Space Reflections", default=False)
    volumetrics: bpy.props.BoolProperty(name="Volumetric Effects", default=False)
    motion_blur: bpy.props.BoolProperty(name="Motion Blur", default=False)
    lod_multiplier: bpy.props.FloatProperty(
        name="LOD Distance Multiplier",
        default=1.0,
        min=0.1,
        max=5.0,
        description="Lower values switch to cheaper LODs sooner",
    )
    max_dynamic_lights: bpy.props.IntProperty(name="Max Dynamic Lights", default=4, min=0)
    max_shadow_casters: bpy.props.IntProperty(name="Max Real-Time Shadow Casters", default=2, min=0)
    physics_quality: bpy.props.EnumProperty(
        name="Physics Quality",
        items=OPTIMIZATION_QUALITY_ITEMS,
        default="MEDIUM",
    )
    animation_update_rate: bpy.props.IntProperty(
        name="Animation Update Rate",
        default=30,
        min=1,
        max=120,
        description="Future runtime animation updates per second for far or lightweight characters",
    )
    animation_quality: bpy.props.EnumProperty(
        name="Animation Quality",
        items=OPTIMIZATION_QUALITY_ITEMS,
        default="MEDIUM",
    )
    particles_quality: bpy.props.EnumProperty(
        name="Particles Quality",
        items=OPTIMIZATION_QUALITY_ITEMS,
        default="MEDIUM",
    )
    vegetation_density: bpy.props.FloatProperty(
        name="Vegetation Density",
        default=0.6,
        min=0.0,
        max=1.0,
        description="Future runtime density for grass, trees, and decorative vegetation",
    )
    reflection_quality: bpy.props.EnumProperty(
        name="Reflection Quality",
        items=OPTIMIZATION_QUALITY_ITEMS,
        default="LOW",
    )
    post_processing_quality: bpy.props.EnumProperty(
        name="Post-Processing Quality",
        items=OPTIMIZATION_QUALITY_ITEMS,
        default="MEDIUM",
    )


class BE_PerformanceBudget(PropertyGroup):
    max_triangles_visible: bpy.props.IntProperty(name="Max Visible Triangles", default=300000, min=0)
    max_draw_calls_estimated: bpy.props.IntProperty(name="Max Estimated Draw Calls", default=800, min=0)
    max_texture_memory_mb: bpy.props.IntProperty(name="Max Texture Memory MB", default=512, min=0)
    max_dynamic_lights: bpy.props.IntProperty(name="Max Dynamic Lights", default=4, min=0)
    max_shadow_casters: bpy.props.IntProperty(name="Max Shadow Casters", default=2, min=0)
    max_rigidbodies: bpy.props.IntProperty(name="Max Rigidbodies", default=80, min=0)
    max_particles: bpy.props.IntProperty(name="Max Particles", default=15000, min=0)
    max_bones_visible: bpy.props.IntProperty(name="Max Visible Bones", default=700, min=0)
    target_fps: bpy.props.IntProperty(name="Target FPS", default=60, min=15, max=240)


class BE_OptimizationSettings(PropertyGroup):
    one_gb_ram_mode: bpy.props.BoolProperty(
        name="1 GB RAM Mode",
        default=True,
        description="Keep runtime budgets strict enough for very weak computers",
    )
    max_runtime_ram_mb: bpy.props.IntProperty(
        name="Runtime RAM MB",
        default=1024,
        min=256,
        description="Maximum runtime memory budget used by build and streaming plans",
    )
    camera_frustum_generation: bpy.props.BoolProperty(
        name="Generate Visible Camera Area Only",
        default=True,
        description="Runtime updates and streams only objects the camera can see or will soon see",
    )
    hide_behind_camera: bpy.props.BoolProperty(
        name="Unload Behind Camera",
        default=True,
        description="Hide or stream out objects behind the active camera",
    )
    hidden_surface_culling: bpy.props.BoolProperty(
        name="Hidden Surface Culling",
        default=True,
        description="Prefer skipping object parts and surfaces the player cannot see",
    )
    texture_streaming: bpy.props.BoolProperty(
        name="Texture Streaming",
        default=True,
        description="Load high texture detail only near and inside the camera view",
    )
    mesh_streaming: bpy.props.BoolProperty(
        name="Mesh Streaming",
        default=True,
        description="Load high mesh detail only near and inside the camera view",
    )
    world_cell_size: bpy.props.FloatProperty(
        name="World Cell Size",
        default=24.0,
        min=1.0,
        description="Grid size used for open-world streaming and unload planning",
    )
    visible_cell_radius: bpy.props.IntProperty(
        name="Visible Cell Radius",
        default=2,
        min=1,
        description="Number of nearby world cells kept active around the camera/player",
    )
    max_visible_objects: bpy.props.IntProperty(
        name="Max Visible Objects",
        default=250,
        min=16,
        description="Runtime target for objects active in the visible camera area",
    )
    generation_budget_ms: bpy.props.FloatProperty(
        name="Generation Budget MS",
        default=3.0,
        min=0.1,
        description="Frame-time budget for streaming/generation work",
    )
    dynamic_resolution: bpy.props.BoolProperty(
        name="Dynamic Resolution",
        default=True,
        description="Automatically lower render scale when the scene becomes too heavy",
    )
    emergency_quality_drop: bpy.props.BoolProperty(
        name="Emergency Quality Drop",
        default=True,
        description="Aggressively lower visuals before the game freezes",
    )
    weak_hardware_target: bpy.props.BoolProperty(
        name="Weak Hardware Target",
        default=True,
        description="Prefer settings that run well on older or weaker computers",
    )
    prefer_baked_lighting: bpy.props.BoolProperty(
        name="Prefer Baked Lighting",
        default=True,
        description="Use baked lighting when possible instead of many real-time lights",
    )
    use_lod_strategy: bpy.props.BoolProperty(
        name="Use LOD Strategy",
        default=True,
        description="Plan cheaper models for far-away objects",
    )
    use_impostors: bpy.props.BoolProperty(
        name="Use Impostor Strategy",
        default=True,
        description="Plan far-distance impostors for complex distant objects",
    )
    use_texture_atlases: bpy.props.BoolProperty(
        name="Use Texture Atlas Strategy",
        default=True,
        description="Prefer shared texture atlases where possible",
    )
    use_material_batching: bpy.props.BoolProperty(
        name="Use Material Batching Strategy",
        default=True,
        description="Prefer shared materials so future batching is easier",
    )
    use_instancing: bpy.props.BoolProperty(
        name="Use Instancing Strategy",
        default=True,
        description="Use future instancing for repeated objects",
    )
    use_occlusion_culling: bpy.props.BoolProperty(
        name="Use Occlusion Culling Strategy",
        default=True,
        description="Plan future occlusion culling for hidden objects",
    )
    use_frustum_culling: bpy.props.BoolProperty(
        name="Use Frustum Culling Strategy",
        default=True,
        description="Future runtime should skip objects outside the camera view",
    )
    use_animation_culling: bpy.props.BoolProperty(
        name="Use Animation Culling",
        default=True,
        description="Update far NPC animations less often",
    )
    use_physics_culling: bpy.props.BoolProperty(
        name="Use Physics Culling and Sleep",
        default=True,
        description="Sleep or disable physics for inactive distant objects",
    )
    use_simplified_colliders: bpy.props.BoolProperty(
        name="Use Simplified Colliders",
        default=True,
        description="Prefer simple colliders for gameplay physics",
    )
    async_asset_loading: bpy.props.BoolProperty(
        name="Async Asset Loading Architecture",
        default=True,
        description="Reserve architecture for future async asset loading",
    )
    level_streaming: bpy.props.BoolProperty(
        name="Level Streaming Architecture",
        default=True,
        description="Reserve architecture for future large-world streaming",
    )
    scalable_post_processing: bpy.props.BoolProperty(
        name="Scalable Post-Processing Profiles",
        default=True,
        description="Use quality profiles for effects instead of one fixed look",
    )
    last_report_summary: bpy.props.StringProperty(
        name="Last Report",
        default="No performance analysis yet.",
    )


class BE_PerformanceReportMessage(PropertyGroup):
    severity: bpy.props.EnumProperty(
        name="Status",
        items=REPORT_SEVERITY_ITEMS,
        default="GOOD",
    )
    message: bpy.props.StringProperty(name="Message", default="")
    suggested_fix: bpy.props.StringProperty(name="Suggested Fix", default="")


class BE_PerformanceReport(PropertyGroup):
    status: bpy.props.EnumProperty(
        name="Overall Status",
        items=REPORT_SEVERITY_ITEMS,
        default="GOOD",
    )
    summary: bpy.props.StringProperty(name="Summary", default="No performance analysis yet.")
    object_count: bpy.props.IntProperty(name="Objects", default=0)
    mesh_count: bpy.props.IntProperty(name="Mesh Objects", default=0)
    camera_count: bpy.props.IntProperty(name="Cameras", default=0)
    triangle_count: bpy.props.IntProperty(name="Estimated Triangles", default=0)
    draw_calls_estimated: bpy.props.IntProperty(name="Estimated Draw Calls", default=0)
    material_count: bpy.props.IntProperty(name="Unique Materials", default=0)
    light_count: bpy.props.IntProperty(name="Lights", default=0)
    dynamic_light_count: bpy.props.IntProperty(name="Dynamic Lights", default=0)
    shadow_caster_count: bpy.props.IntProperty(name="Real-Time Shadow Casters", default=0)
    rigidbody_count: bpy.props.IntProperty(name="Rigidbodies", default=0)
    particle_system_count: bpy.props.IntProperty(name="Particle Systems", default=0)
    particle_count_estimated: bpy.props.IntProperty(name="Estimated Particles", default=0)
    bone_count_visible: bpy.props.IntProperty(name="Visible Bones", default=0)
    texture_count: bpy.props.IntProperty(name="Images", default=0)
    texture_memory_mb: bpy.props.FloatProperty(name="Estimated Texture Memory MB", default=0.0, min=0.0)
    objects_without_lod: bpy.props.IntProperty(name="Objects Without LOD", default=0)
    dynamic_object_count: bpy.props.IntProperty(name="Dynamic Objects", default=0)
    messages: bpy.props.CollectionProperty(type=BE_PerformanceReportMessage)
    active_message_index: bpy.props.IntProperty(default=0)


class BE_EditorToolSettings(PropertyGroup):
    active_bottom_tab: bpy.props.EnumProperty(
        name="Bottom Panel",
        items=EDITOR_BOTTOM_TAB_ITEMS,
        default="ASSETS",
    )
    object_snap: bpy.props.BoolProperty(name="Object Snap", default=True)
    grid_snap: bpy.props.BoolProperty(name="Grid Snap", default=True)
    physics_preview: bpy.props.BoolProperty(name="Physics Preview", default=False)
    lighting_preview: bpy.props.BoolProperty(name="Lighting Preview", default=True)
    ai_navigation_preview: bpy.props.BoolProperty(name="AI Navigation Preview", default=False)
    collision_preview: bpy.props.BoolProperty(name="Collision Preview", default=False)
    performance_heatmap: bpy.props.BoolProperty(name="Performance Heatmap", default=False)
    camera_preview: bpy.props.BoolProperty(name="Camera Preview", default=True)
    multiplayer_preview: bpy.props.BoolProperty(name="Multiplayer Preview", default=False)
    show_beginner_labels: bpy.props.BoolProperty(name="Beginner Labels", default=True)
    hide_non_game_menus: bpy.props.BoolProperty(name="Hide Non-Game Menus", default=True)
    input_lock_enabled: bpy.props.BoolProperty(
        name="Game Input Lock",
        default=True,
        description="Stop Blender modeling shortcuts from stealing WASD and gameplay keys in BlendEngine",
    )
    input_lock_running: bpy.props.BoolProperty(name="Input Lock Running", default=False)


class BE_MultiplayerSettings(PropertyGroup):
    enabled: bpy.props.BoolProperty(name="Multiplayer", default=False)
    mode: bpy.props.EnumProperty(
        name="Mode",
        items=MULTIPLAYER_MODE_ITEMS,
        default="SINGLE_PLAYER",
    )
    sync_position: bpy.props.BoolProperty(name="Position", default=True)
    sync_health: bpy.props.BoolProperty(name="Health", default=True)
    sync_inventory: bpy.props.BoolProperty(name="Inventory", default=True)
    sync_animation: bpy.props.BoolProperty(name="Animation", default=True)
    predicted_movement: bpy.props.BoolProperty(name="Predicted Movement", default=True)
    rollback_safety: bpy.props.BoolProperty(name="Rollback Safety", default=False)
    max_players: bpy.props.IntProperty(name="Max Players", default=4, min=1, max=256)
    server_tick_rate: bpy.props.IntProperty(name="Server Tick Rate", default=30, min=5, max=240)
    port: bpy.props.IntProperty(name="Port", default=7777, min=1, max=65535)


classes = (
    BE_GameEvent,
    BE_GameCondition,
    BE_GameAction,
    BE_GameBehavior,
    BE_GameVariable,
    BE_GameObjectComponent,
    BE_PlayerControllerSettings,
    BE_NPCBehaviorSettings,
    BE_HealthSettings,
    BE_AnimationState,
    BE_AnimationTransition,
    BE_AnimationControllerSettings,
    BE_ObjectOptimizationSettings,
    BE_ObjectSettings,
    BE_InputBinding,
    BE_InputMap,
    BE_ProjectSettings,
    BE_ExportSettings,
    BE_GameQualityProfile,
    BE_PerformanceBudget,
    BE_OptimizationSettings,
    BE_PerformanceReportMessage,
    BE_PerformanceReport,
    BE_EditorToolSettings,
    BE_MultiplayerSettings,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.blendengine_project = bpy.props.PointerProperty(type=BE_ProjectSettings)
    bpy.types.Scene.blendengine_input_map = bpy.props.PointerProperty(type=BE_InputMap)
    bpy.types.Scene.blendengine_export = bpy.props.PointerProperty(type=BE_ExportSettings)
    bpy.types.Scene.blendengine_quality_profile = bpy.props.PointerProperty(type=BE_GameQualityProfile)
    bpy.types.Scene.blendengine_performance_budget = bpy.props.PointerProperty(type=BE_PerformanceBudget)
    bpy.types.Scene.blendengine_optimization = bpy.props.PointerProperty(type=BE_OptimizationSettings)
    bpy.types.Scene.blendengine_performance_report = bpy.props.PointerProperty(type=BE_PerformanceReport)
    bpy.types.Scene.blendengine_editor = bpy.props.PointerProperty(type=BE_EditorToolSettings)
    bpy.types.Scene.blendengine_multiplayer = bpy.props.PointerProperty(type=BE_MultiplayerSettings)
    bpy.types.Object.blendengine_object = bpy.props.PointerProperty(type=BE_ObjectSettings)


def unregister():
    for attr in (
        "blendengine_project",
        "blendengine_input_map",
        "blendengine_export",
        "blendengine_quality_profile",
        "blendengine_performance_budget",
        "blendengine_optimization",
        "blendengine_performance_report",
        "blendengine_editor",
        "blendengine_multiplayer",
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
    if hasattr(bpy.types.Object, "blendengine_object"):
        del bpy.types.Object.blendengine_object

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
