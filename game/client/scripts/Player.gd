extends CharacterBody3D
## Third-person character controller (Fortnite-style feel: run, sprint, jump).
##
## This is a placeholder capsule. Swap the MeshInstance3D for a real rigged
## character model later — the movement/camera rig stays the same.

@export var walk_speed: float = 6.0
@export var sprint_speed: float = 10.0
@export var jump_velocity: float = 8.0
@export var mouse_sensitivity: float = 0.003
@export var max_jumps: int = 1  ## raise to 2 when the Double Jump skill unlocks

var _jumps_left: int = 0
var _gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity", 9.8)

@onready var _spring_arm: SpringArm3D = $CameraPivot/SpringArm3D
@onready var _pivot: Node3D = $CameraPivot


func _ready() -> void:
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		# Yaw rotates the whole body; pitch only tilts the camera pivot.
		rotate_y(-event.relative.x * mouse_sensitivity)
		_pivot.rotate_x(-event.relative.y * mouse_sensitivity)
		_pivot.rotation.x = clamp(_pivot.rotation.x, deg_to_rad(-70), deg_to_rad(70))
	elif event.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


func _physics_process(delta: float) -> void:
	# Gravity.
	if not is_on_floor():
		velocity.y -= _gravity * delta
	else:
		_jumps_left = max_jumps

	# Jump (supports multi-jump for the Mobility skill tree).
	if Input.is_action_just_pressed("jump") and _jumps_left > 0:
		velocity.y = jump_velocity
		_jumps_left -= 1

	# Planar movement relative to where the body faces.
	var input_dir := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var direction := (transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
	var speed := sprint_speed if Input.is_action_pressed("sprint") else walk_speed

	if direction:
		velocity.x = direction.x * speed
		velocity.z = direction.z * speed
	else:
		velocity.x = move_toward(velocity.x, 0, speed)
		velocity.z = move_toward(velocity.z, 0, speed)

	move_and_slide()
