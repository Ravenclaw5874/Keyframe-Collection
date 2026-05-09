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


class KFPopupItem(bpy.types.PropertyGroup):
    col_name: bpy.props.StringProperty()
    is_selected: bpy.props.BoolProperty(default=False)


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


class KFCOLLECTION_UL_popup_list(bpy.types.UIList):
    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname
    ):
        row = layout.row(align=True)
        row.prop(item, "is_selected", text="")
        row.label(text=item.col_name, icon="OUTLINER_COLLECTION")


# --- [4] 통합 관리 오퍼레이터 (팝업창) ---
class KFCOLLECTION_OT_manage(bpy.types.Operator):
    bl_idname = "kf_collection.manage"
    bl_label = "Manage Collections"
    bl_description = "Add or remove collections to control"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        scene = context.scene
        wm = context.window_manager
        wm.kf_popup_items.clear()

        ctrl_obj = scene.kf_ctrl_obj

        if ctrl_obj:
            if all(item.sort_index == 0 for item in ctrl_obj.kf_collections):
                for i, item in enumerate(ctrl_obj.kf_collections):
                    item.sort_index = i

            # 아웃라이너에서 컬렉션이 삭제된 경우 처리 (PointerProperty가 끊어진 슬롯)
            for i, item in enumerate(ctrl_obj.kf_collections):
                if not item.collection and item.is_managed:
                    item.is_managed = False

                    if ctrl_obj.animation_data and ctrl_obj.animation_data.action:
                        action = ctrl_obj.animation_data.action
                        paths = [
                            f"kf_collections[{i}].kf_hide_viewport",
                            f"kf_collections[{i}].kf_hide_render",
                            f'kf_collections["{item.name}"].kf_hide_viewport',
                            f'kf_collections["{item.name}"].kf_hide_render',
                        ]
                        for fc in list(action.fcurves):
                            if fc.data_path in paths:
                                fc.data_path = fc.data_path.replace(
                                    "kf_hide_", "MISSING_kf_hide_"
                                )

        existing_cols = set()

        if ctrl_obj:
            existing_cols = {
                item.collection.name
                for item in ctrl_obj.kf_collections
                if item.collection and item.is_managed
            }

        for col in bpy.data.collections:
            new_item = wm.kf_popup_items.add()
            new_item.name = col.name
            new_item.col_name = col.name
            new_item.is_selected = col.name in existing_cols

        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        if len(wm.kf_popup_items) == 0:
            layout.label(text="No collections in the scene.", icon="INFO")
            return

        layout.label(text="Check to add, uncheck to remove:")
        layout.template_list(
            "KFCOLLECTION_UL_popup_list",
            "",
            wm,
            "kf_popup_items",
            wm,
            "kf_popup_index",
            rows=10,
        )

    def execute(self, context):
        scene = context.scene
        wm = context.window_manager
        any_checked = any(item.is_selected for item in wm.kf_popup_items)

        ctrl_obj = scene.kf_ctrl_obj
        if any_checked and not ctrl_obj:
            ctrl_obj = bpy.data.objects.new(CTRL_NAME, None)
            ctrl_obj.empty_display_type = "ARROWS"
            scene.collection.objects.link(ctrl_obj)
            scene.kf_ctrl_obj = ctrl_obj

        if ctrl_obj:
            existing_cols = {
                item.collection.name
                for item in ctrl_obj.kf_collections
                if item.collection and item.is_managed
            }

            items_to_add = []
            items_to_remove = []

            for p_item in wm.kf_popup_items:
                if p_item.is_selected and p_item.col_name not in existing_cols:
                    items_to_add.append(p_item.col_name)
                elif not p_item.is_selected and p_item.col_name in existing_cols:
                    items_to_remove.append(p_item.col_name)

            for i, item in enumerate(ctrl_obj.kf_collections):
                if item.collection and item.collection.name in items_to_remove:
                    item.is_managed = False

                    if ctrl_obj.animation_data and ctrl_obj.animation_data.action:
                        action = ctrl_obj.animation_data.action
                        paths = [
                            f"kf_collections[{i}].kf_hide_viewport",
                            f"kf_collections[{i}].kf_hide_render",
                            f'kf_collections["{item.name}"].kf_hide_viewport',
                            f'kf_collections["{item.name}"].kf_hide_render',
                        ]
                        for fc in list(action.fcurves):
                            if fc.data_path in paths:
                                fc.data_path = fc.data_path.replace(
                                    "kf_hide_", "MISSING_kf_hide_"
                                )

            for name in items_to_add:
                col = bpy.data.collections.get(name)
                if col:
                    max_sort = max(
                        [item.sort_index for item in ctrl_obj.kf_collections] + [-1]
                    )

                    # 이름이 아닌 순수 컬렉션 참조(포인터)로 기존 슬롯 탐색
                    existing_idx = -1
                    for idx, item in enumerate(ctrl_obj.kf_collections):
                        if item.collection == col:
                            existing_idx = idx
                            break

                    if existing_idx >= 0:
                        new_item = ctrl_obj.kf_collections[existing_idx]
                        new_item.is_managed = True
                        new_item.name = col.name
                        new_item.sort_index = max_sort + 1

                        if ctrl_obj.animation_data and ctrl_obj.animation_data.action:
                            action = ctrl_obj.animation_data.action
                            disabled_paths = [
                                f"kf_collections[{existing_idx}].MISSING_kf_hide_viewport",
                                f"kf_collections[{existing_idx}].MISSING_kf_hide_render",
                                f'kf_collections["{col.name}"].MISSING_kf_hide_viewport',
                                f'kf_collections["{col.name}"].MISSING_kf_hide_render',
                            ]
                            for fc in list(action.fcurves):
                                if fc.data_path in disabled_paths:
                                    fc.data_path = fc.data_path.replace(
                                        "MISSING_kf_hide_", "kf_hide_"
                                    )
                    else:
                        new_item = ctrl_obj.kf_collections.add()
                        new_item.collection = col
                        new_item.name = col.name
                        new_item.is_managed = True
                        new_item.sort_index = max_sort + 1
                        new_item.kf_hide_viewport = col.hide_viewport
                        new_item.kf_hide_render = col.hide_render

            max_idx = max(0, len(ctrl_obj.kf_collections) - 1)
            if ctrl_obj.kf_collections_index > max_idx:
                ctrl_obj.kf_collections_index = max_idx

        wm.kf_popup_items.clear()
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

        # 안전장치: sort_index가 모두 0이거나 중복이 있으면 초기화
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

        if ctrl_obj and len(ctrl_obj.kf_collections) > 0:
            row = layout.row()
            row.template_list(
                "KFCOLLECTION_UL_list",
                "",
                ctrl_obj,
                "kf_collections",
                ctrl_obj,
                "kf_collections_index",
            )

            col = row.column(align=True)
            col.operator("kf_collection.manage", icon="PREFERENCES", text="")
            col.separator()
            col.operator("kf_collection.move", icon="TRIA_UP", text="").direction = "UP"
            col.operator(
                "kf_collection.move", icon="TRIA_DOWN", text=""
            ).direction = "DOWN"
        else:
            layout.operator(
                "kf_collection.manage", text="Manage Collections", icon="PREFERENCES"
            )


# --- [6] 애니메이션 동기화 핸들러 ---
@persistent
def kf_collection_handler(scene):
    ctrl_obj = scene.kf_ctrl_obj
    if not ctrl_obj:
        return

    is_changed = False

    for item in ctrl_obj.kf_collections:
        if item.collection and item.is_managed:
            if item.collection.hide_viewport != item.kf_hide_viewport:
                item.collection.hide_viewport = item.kf_hide_viewport
                is_changed = True
            if item.collection.hide_render != item.kf_hide_render:
                item.collection.hide_render = item.kf_hide_render
                is_changed = True

    if is_changed and not bpy.app.background:
        if getattr(bpy.context, "view_layer", None):
            bpy.context.view_layer.update()


# --- [6.5] 이름 동기화 핸들러 (아웃라이너 이름 변경 감지) ---
@persistent
def kf_collection_depsgraph_handler(scene, depsgraph):
    ctrl_obj = scene.kf_ctrl_obj
    if not ctrl_obj:
        return

    for item in ctrl_obj.kf_collections:
        if item.collection and item.is_managed and item.name != item.collection.name:
            old_name = item.name
            new_name = item.collection.name
            item.name = new_name

            if old_name == "":
                continue

            if ctrl_obj.animation_data and ctrl_obj.animation_data.action:
                action = ctrl_obj.animation_data.action
                for fc in action.fcurves:
                    if f'["{old_name}"]' in fc.data_path:
                        fc.data_path = fc.data_path.replace(
                            f'["{old_name}"]', f'["{new_name}"]'
                        )
                    elif f"['{old_name}']" in fc.data_path:
                        fc.data_path = fc.data_path.replace(
                            f"['{old_name}']", f'["{new_name}"]'
                        )


# --- [7] 등록 및 해제 ---
classes = (
    KFCollectionItem,
    KFPopupItem,
    KFCOLLECTION_UL_list,
    KFCOLLECTION_UL_popup_list,
    KFCOLLECTION_OT_manage,
    KFCOLLECTION_OT_move,
    KFCOLLECTION_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.kf_collections = bpy.props.CollectionProperty(
        type=KFCollectionItem
    )
    bpy.types.Object.kf_collections_index = bpy.props.IntProperty()

    bpy.types.WindowManager.kf_popup_items = bpy.props.CollectionProperty(
        type=KFPopupItem
    )
    bpy.types.WindowManager.kf_popup_index = bpy.props.IntProperty()

    bpy.types.Scene.kf_ctrl_obj = bpy.props.PointerProperty(type=bpy.types.Object)

    if kf_collection_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(kf_collection_handler)
    if kf_collection_depsgraph_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(kf_collection_depsgraph_handler)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Object.kf_collections
    del bpy.types.Object.kf_collections_index
    del bpy.types.WindowManager.kf_popup_items
    del bpy.types.WindowManager.kf_popup_index
    del bpy.types.Scene.kf_ctrl_obj

    if kf_collection_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(kf_collection_handler)
    if kf_collection_depsgraph_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(kf_collection_depsgraph_handler)


if __name__ == "__main__":
    register()
