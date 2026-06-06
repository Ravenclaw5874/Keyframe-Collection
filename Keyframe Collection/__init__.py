bl_info = {
    "name": "Keyframe Collection",
    "author": "R4V3N",
    "version": (1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > N-Panel > Keyframe Collection",
    "description": "Allows you to add keyframes or drivers to collection visibility.",
    "category": "Animation",
}

import bpy
from bpy.app.handlers import persistent

# 사용할 전용 컨트롤러 오브젝트의 이름 (고정)
CTRL_NAME = "KF_Collection_Ctrl"


# --- [1] 동기화 업데이트 함수 ---
def update_viewport(self, context):
    if self.collection:
        self.collection.hide_viewport = self.kf_hide_viewport


def update_render(self, context):
    if self.collection:
        self.collection.hide_render = self.kf_hide_render


# --- [2] 데이터 구조 ---
class KFCollectionItem(bpy.types.PropertyGroup):
    collection: bpy.props.PointerProperty(name="Collection", type=bpy.types.Collection)
    is_managed: bpy.props.BoolProperty(default=True)
    sort_index: bpy.props.IntProperty(default=0)
    kf_hide_viewport: bpy.props.BoolProperty(
        name="Hide in Viewport", default=False, update=update_viewport
    )
    kf_hide_render: bpy.props.BoolProperty(
        name="Disable in Render", default=False, update=update_render
    )


# --- [3] UI 리스트 렌더링 ---
class KFCOLLECTION_UL_list(bpy.types.UIList):
    def filter_items(self, context, data, propname):
        collections = getattr(data, propname)
        flt_flags = []
        for item in collections:
            if item.collection and item.is_managed:
                flt_flags.append(self.bitflag_filter_item)
            else:
                flt_flags.append(0)

        if self.filter_name:
            for i, item in enumerate(collections):
                if flt_flags[i] & self.bitflag_filter_item:
                    if self.filter_name.lower() not in item.name.lower():
                        if not self.use_filter_invert:
                            flt_flags[i] &= ~self.bitflag_filter_item
                    else:
                        if self.use_filter_invert:
                            flt_flags[i] &= ~self.bitflag_filter_item

        if self.use_filter_sort_alpha:
            indexed_items = [
                (i, item.name.lower()) for i, item in enumerate(collections)
            ]
        else:
            indexed_items = [(i, item.sort_index) for i, item in enumerate(collections)]

        indexed_items.sort(key=lambda x: x[1])

        flt_neworder = [0] * len(collections)
        for visual_pos, (original_idx, _) in enumerate(indexed_items):
            flt_neworder[original_idx] = visual_pos

        return flt_flags, flt_neworder

    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname
    ):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            if item.collection:
                row.prop(
                    item.collection,
                    "name",
                    text="",
                    emboss=False,
                    icon="OUTLINER_COLLECTION",
                )

                icon_viewport = (
                    "RESTRICT_VIEW_OFF"
                    if not item.kf_hide_viewport
                    else "RESTRICT_VIEW_ON"
                )
                row.prop(item, "kf_hide_viewport", text="", icon=icon_viewport)

                icon_render = (
                    "RESTRICT_RENDER_OFF"
                    if not item.kf_hide_render
                    else "RESTRICT_RENDER_ON"
                )
                row.prop(item, "kf_hide_render", text="", icon=icon_render)
            else:
                row.label(text="No Collection", icon="ERROR")


# --- 이름 동기화 함수 (Depsgraph 낭비 제거용) ---
def sync_collection_names(ctrl_obj):
    if not ctrl_obj:
        return

    rename_map = {}
    for item in ctrl_obj.kf_collections:
        if item.collection and item.name != item.collection.name:
            if item.name != "":
                rename_map[item.name] = item.collection.name
            item.name = item.collection.name

    if rename_map and ctrl_obj.animation_data and ctrl_obj.animation_data.action:
        action = ctrl_obj.animation_data.action
        for fc in action.fcurves:
            for old_name, new_name in rename_map.items():
                if f'["{old_name}"]' in fc.data_path:
                    fc.data_path = fc.data_path.replace(
                        f'["{old_name}"]', f'["{new_name}"]'
                    )
                elif f"['{old_name}']" in fc.data_path:
                    fc.data_path = fc.data_path.replace(
                        f"['{old_name}']", f'["{new_name}"]'
                    )


# --- [4] 통합 관리 오퍼레이터 (Add/Remove 교체) ---
class KFCOLLECTION_OT_add(bpy.types.Operator):
    bl_idname = "kf_collection.add"
    bl_label = "Add Active Collection"
    bl_description = "Add the currently active collection in the outliner to the list"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.collection is not None

    def execute(self, context):
        scene = context.scene
        col = context.collection

        ctrl_obj = scene.kf_ctrl_obj
        if not ctrl_obj:
            ctrl_obj = bpy.data.objects.new(CTRL_NAME, None)
            ctrl_obj.empty_display_type = "ARROWS"
            scene.collection.objects.link(ctrl_obj)
            scene.kf_ctrl_obj = ctrl_obj

        sync_collection_names(ctrl_obj)

        existing_idx = -1
        for idx, item in enumerate(ctrl_obj.kf_collections):
            if item.collection == col:
                existing_idx = idx
                break

        if existing_idx >= 0:
            new_item = ctrl_obj.kf_collections[existing_idx]
            if new_item.is_managed:
                return {"CANCELLED"}

            new_item.is_managed = True
            new_item.name = col.name
            max_sort = max([item.sort_index for item in ctrl_obj.kf_collections] + [-1])
            new_item.sort_index = max_sort + 1

            # F-curve 최적화: 추가 시 단일 패스 순회
            if ctrl_obj.animation_data and ctrl_obj.animation_data.action:
                action = ctrl_obj.animation_data.action
                disabled_paths = {
                    f"kf_collections[{existing_idx}].MISSING_kf_hide_viewport",
                    f"kf_collections[{existing_idx}].MISSING_kf_hide_render",
                    f'kf_collections["{col.name}"].MISSING_kf_hide_viewport',
                    f'kf_collections["{col.name}"].MISSING_kf_hide_render',
                }
                for fc in action.fcurves:
                    if fc.data_path in disabled_paths:
                        fc.data_path = fc.data_path.replace(
                            "MISSING_kf_hide_", "kf_hide_"
                        )

        else:
            new_item = ctrl_obj.kf_collections.add()
            new_item.collection = col
            new_item.name = col.name
            new_item.is_managed = True
            max_sort = max([item.sort_index for item in ctrl_obj.kf_collections] + [-1])
            new_item.sort_index = max_sort + 1
            new_item.kf_hide_viewport = col.hide_viewport
            new_item.kf_hide_render = col.hide_render

        ctrl_obj.kf_collections_index = len(ctrl_obj.kf_collections) - 1

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

        return {"FINISHED"}


class KFCOLLECTION_OT_remove(bpy.types.Operator):
    bl_idname = "kf_collection.remove"
    bl_label = "Remove Selected Collection"
    bl_description = "Remove the selected collection from the list"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ctrl_obj = context.scene.kf_ctrl_obj
        return ctrl_obj and len(ctrl_obj.kf_collections) > 0

    def execute(self, context):
        ctrl_obj = context.scene.kf_ctrl_obj
        idx = ctrl_obj.kf_collections_index

        if idx < 0 or idx >= len(ctrl_obj.kf_collections):
            return {"CANCELLED"}

        item = ctrl_obj.kf_collections[idx]
        if not item.is_managed:
            return {"CANCELLED"}

        sync_collection_names(ctrl_obj)

        item.is_managed = False

        # F-curve 최적화: 삭제 시 단일 패스 순회
        if ctrl_obj.animation_data and ctrl_obj.animation_data.action:
            action = ctrl_obj.animation_data.action
            paths = {
                f"kf_collections[{idx}].kf_hide_viewport",
                f"kf_collections[{idx}].kf_hide_render",
                f'kf_collections["{item.name}"].kf_hide_viewport',
                f'kf_collections["{item.name}"].kf_hide_render',
            }
            for fc in action.fcurves:
                if fc.data_path in paths:
                    fc.data_path = fc.data_path.replace("kf_hide_", "MISSING_kf_hide_")

        # 보이는 아이템 목록을 기준으로 새 인덱스 위치 보정 시도
        visible_indices = [
            i for i, it in enumerate(ctrl_obj.kf_collections) if it.is_managed
        ]
        if visible_indices:
            ctrl_obj.kf_collections_index = visible_indices[-1]
        else:
            ctrl_obj.kf_collections_index = 0

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

        return {"FINISHED"}


# --- [4.5] 리스트 순서 변경 오퍼레이터 ---
class KFCOLLECTION_OT_move(bpy.types.Operator):
    bl_idname = "kf_collection.move"
    bl_label = "Move Collection"
    bl_description = "Move the selected collection up or down"
    bl_options = {"REGISTER", "INTERNAL"}

    direction: bpy.props.EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])

    @classmethod
    def poll(cls, context):
        ctrl_obj = context.scene.kf_ctrl_obj
        return ctrl_obj and len(ctrl_obj.kf_collections) > 0

    def execute(self, context):
        ctrl_obj = context.scene.kf_ctrl_obj
        idx = ctrl_obj.kf_collections_index

        sort_indices = [item.sort_index for item in ctrl_obj.kf_collections]
        if len(set(sort_indices)) < len(sort_indices):
            for i, item in enumerate(ctrl_obj.kf_collections):
                item.sort_index = i

        visible_items = []
        for i, item in enumerate(ctrl_obj.kf_collections):
            if item.collection and item.is_managed:
                visible_items.append(i)

        visible_items.sort(key=lambda i: ctrl_obj.kf_collections[i].sort_index)

        try:
            visual_pos = visible_items.index(idx)
        except ValueError:
            return {"CANCELLED"}

        if self.direction == "UP" and visual_pos > 0:
            neighbor_idx = visible_items[visual_pos - 1]
        elif self.direction == "DOWN" and visual_pos < len(visible_items) - 1:
            neighbor_idx = visible_items[visual_pos + 1]
        else:
            return {"CANCELLED"}

        temp = ctrl_obj.kf_collections[idx].sort_index
        ctrl_obj.kf_collections[idx].sort_index = ctrl_obj.kf_collections[
            neighbor_idx
        ].sort_index
        ctrl_obj.kf_collections[neighbor_idx].sort_index = temp

        return {"FINISHED"}


# --- [5] N-패널 UI 구성 ---
class KFCOLLECTION_PT_panel(bpy.types.Panel):
    bl_label = "Keyframe Collection"
    bl_idname = "KFCOLLECTION_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Keyframe Collection"

    def draw(self, context):
        layout = self.layout
        ctrl_obj = context.scene.kf_ctrl_obj

        row = layout.row()

        if ctrl_obj:
            data_ptr = ctrl_obj
            prop_name = "kf_collections"
            idx_name = "kf_collections_index"
        else:
            data_ptr = context.scene
            prop_name = "kf_dummy_collections"
            idx_name = "kf_dummy_index"

        row.template_list(
            "KFCOLLECTION_UL_list",
            "",
            data_ptr,
            prop_name,
            data_ptr,
            idx_name,
        )

        col = row.column(align=True)
        col.operator("kf_collection.add", icon="ADD", text="")
        col.operator("kf_collection.remove", icon="REMOVE", text="")
        col.separator()
        col.operator("kf_collection.move", icon="TRIA_UP", text="").direction = "UP"
        col.operator("kf_collection.move", icon="TRIA_DOWN", text="").direction = "DOWN"


# --- [6] 애니메이션 동기화 핸들러 ---
def shift_kf_hide_render_keyframes(scene, shift_amount):
    ctrl_obj = scene.kf_ctrl_obj
    if (
        not ctrl_obj
        or not ctrl_obj.animation_data
        or not ctrl_obj.animation_data.action
    ):
        return

    action = ctrl_obj.animation_data.action

    # F-curve 최적화: 변경해야 할 타겟 경로를 미리 취합 (단일 패스 순회)
    target_paths = set()
    for i, item in enumerate(ctrl_obj.kf_collections):
        if item.collection and item.is_managed:
            target_paths.add(f"kf_collections[{i}].kf_hide_render")
            target_paths.add(f'kf_collections["{item.name}"].kf_hide_render')
            target_paths.add(f"kf_collections['{item.name}'].kf_hide_render")

    if not target_paths:
        return

    for fc in action.fcurves:
        if fc.data_path in target_paths:
            for kp in fc.keyframe_points:
                kp.co[0] += shift_amount
                kp.handle_left[0] += shift_amount
                kp.handle_right[0] += shift_amount
            fc.update()


@persistent
def kf_render_set(scene):
    scene.kf_original_frame = scene.frame_current

    start_frame = (
        scene.frame_preview_start if scene.use_preview_range else scene.frame_start
    )

    if scene.frame_current != start_frame:
        scene.frame_set(start_frame)

    # 렌더링 시작 시 키프레임 물리적 이동 보호장치 (크래쉬 후 재개 시 이중 쉬프트 방지)
    if not scene.kf_is_shifted:
        shift_kf_hide_render_keyframes(scene, -1.0)
        scene.kf_is_shifted = True


@persistent
def kf_render_clear(scene):
    # 렌더 종료/취소 시 원상복구 로직 실행
    if scene.kf_is_shifted:
        shift_kf_hide_render_keyframes(scene, 1.0)
        scene.kf_is_shifted = False

    if scene.kf_original_frame != -1:
        if scene.frame_current != scene.kf_original_frame:
            scene.frame_set(scene.kf_original_frame)
        scene.kf_original_frame = -1


@persistent
def kf_collection_handler(scene):
    ctrl_obj = scene.kf_ctrl_obj
    if not ctrl_obj:
        return

    for item in ctrl_obj.kf_collections:
        if item.collection and item.is_managed:
            if item.collection.hide_viewport != item.kf_hide_viewport:
                item.collection.hide_viewport = item.kf_hide_viewport
            if item.collection.hide_render != item.kf_hide_render:
                item.collection.hide_render = item.kf_hide_render


# --- [7] 등록 및 해제 ---
classes = (
    KFCollectionItem,
    KFCOLLECTION_UL_list,
    KFCOLLECTION_OT_add,
    KFCOLLECTION_OT_remove,
    KFCOLLECTION_OT_move,
    KFCOLLECTION_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    handler_lists = [
        bpy.app.handlers.frame_change_post,
        bpy.app.handlers.render_init,
        bpy.app.handlers.render_complete,
        bpy.app.handlers.render_cancel,
    ]
    target_names = [
        "kf_collection_handler",
        "kf_render_set",
        "kf_render_clear",
    ]
    for h_list in handler_lists:
        for func in reversed(h_list):
            if hasattr(func, "__name__") and func.__name__ in target_names:
                h_list.remove(func)

    bpy.types.Object.kf_collections = bpy.props.CollectionProperty(
        type=KFCollectionItem
    )
    bpy.types.Object.kf_collections_index = bpy.props.IntProperty()
    bpy.types.Scene.kf_ctrl_obj = bpy.props.PointerProperty(type=bpy.types.Object)

    # 씬 종속 속성 등록 (전역 변수 대체)
    bpy.types.Scene.kf_original_frame = bpy.props.IntProperty(default=-1)
    bpy.types.Scene.kf_is_shifted = bpy.props.BoolProperty(default=False)

    # 빈 리스트 렌더링을 위한 더미 속성
    bpy.types.Scene.kf_dummy_collections = bpy.props.CollectionProperty(
        type=KFCollectionItem
    )
    bpy.types.Scene.kf_dummy_index = bpy.props.IntProperty()

    if kf_collection_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(kf_collection_handler)

    if kf_render_set not in bpy.app.handlers.render_init:
        bpy.app.handlers.render_init.append(kf_render_set)
    if kf_render_clear not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(kf_render_clear)
        bpy.app.handlers.render_cancel.append(kf_render_clear)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Object.kf_collections
    del bpy.types.Object.kf_collections_index
    del bpy.types.Scene.kf_ctrl_obj

    del bpy.types.Scene.kf_original_frame
    del bpy.types.Scene.kf_is_shifted
    del bpy.types.Scene.kf_dummy_collections
    del bpy.types.Scene.kf_dummy_index

    if kf_collection_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(kf_collection_handler)

    if kf_render_set in bpy.app.handlers.render_init:
        bpy.app.handlers.render_init.remove(kf_render_set)
    if kf_render_clear in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(kf_render_clear)
    if kf_render_clear in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.remove(kf_render_clear)


if __name__ == "__main__":
    register()
