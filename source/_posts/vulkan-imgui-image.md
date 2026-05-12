---
title: Integrating ImGui Image Display Widget in Muyo Vulkan Renderer
date: 2022-05-22 06:00
lang: en
category: vulkan
tags: vulkan, rendering, graphics, imgui
---

![result](https://i.imgur.com/m7mhHiP.png)

`ImGui` comes with a handy image widget in their demo page. It works magically in my engine to display the built-in font textures, even though I didn't explicitly bind it during the runtime. The `ImGui::Image()` function to draw pictures has a `textureId`, which is also unclear to me.

Since I'm writing my own rendering backend, I took some time to investigate how the `textureId` works.
When we call `ImGui::Image(textureId, ...)`, ImGui creates a draw command to draw a rectangle, and set the  `ImDrawCmd::TextureId` variable with the `textureId` we pass in.
During the execution time, `ImDrawCmd::TextureId` is accessible when we prepare the GPU command buffer.
 That said, `TextureId` serves simply as an index of the texture we want to bind. We have to implement the array of *texture information structure* that can be bond to pipeline when we record the command buffer.

## A Fast Solution

In the [issue](https://github.com/ocornut/imgui/issues/1641) the author of ImGui has discussed to wrap the texture into a `VkDescriptorSet` handle, and pass it as `textureId`. It works as the fact that `typedef void* ImTextureID` has 64 bits on a 64-bit machine, while `VkDescriptorSet` has also 64 bits. However, this doesn't hold on a 32-bit machines. That's reason why the Vulkan ImGui demo implementation has no implementation of `ImGui::Image()` yet.

## Not That Fast Solution

The fast solution inspired me that I can track descriptor sets with `textureId`. In my solution, I use my [DescriptorManager](https://github.com/v3c70r/Muyo/blob/0ad38fbcdc68ea47930ae9f7a0dd602ea01a3ddf/src/DescriptorManager.h#L203) to create and track a list of descriptor sets used in ImGui, where the list is addressed by `textureId`. I also keep a map from resource identifier to `textureId` so that I can use bind the resource when I draw image with `ImGui::Image()`.

```C++
    std::vector<VkDescriptorSet> m_vImGuiTextureDescriptorSets;
    std::map<std::string, size_t> m_mImGuiTextureIds;
```

Note that the first `textureId` is reserved for font textures. `ImDrawCmd::TextureId` is zero when there's no `ImGui::Image()` called on the draw command. To honour this, I have to insert the font texture as the first ImGui texture when creating resources for ImGui.

```C++
    // Create font texture
    unsigned char* fontData;
    int texWidth, texHeight;
    io.Fonts->GetTexDataAsRGBA32(&fontData, &texWidth, &texHeight);

    // UI font texture has texture id of 0. It has to be inserted before other texture
    GetRenderResourceManager()->GetTexture("ui_font_texture", fontData, texWidth, texHeight);
    GetDescriptorManager()->GetImGuiTextureId("ui_font_texture");
```

The other textures can be inserted with the same fashion. For example, I can display my environment map with ImGui like this.

```C++
//...
ImTextureID my_tex_id = (void*)GetDescriptorManager()->GetImGuiTextureId("EnvMap");
//...
ImGui::Image(my_tex_id, ImVec2(my_tex_w, my_tex_h), uv_min, uv_max, tint_col, border_col);
```

During the draw call, we can simply bind the corresponding descriptor set based on the `TextureId` in draw command like [this](https://github.com/v3c70r/Muyo/blob/0ad38fbcdc68ea47930ae9f7a0dd602ea01a3ddf/src/RenderPassUI.cpp#L265).

```C++
vkCmdBindDescriptorSets(curCmdBuf, VK_PIPELINE_BIND_POINT_GRAPHICS, m_pipelineLayout, 0, 1, &GetDescriptorManager()->GetImGuiTextureDescriptorSet((size_t)drawCmd.TextureId), 0, nullptr);
```

