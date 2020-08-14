Title: Render to CubeMap with Vulkan Multiview
Slug: vulkan-multiview
Date: 2020-08-13 06:00
Lang: en
Category: vulkan
Tags: vulkan, rendering, graphics, pbr
Author: Qing Gu
Summary: How to use Multivew render pass in Vulkan to render to cube maps

## Render to CubeMap with Vulkan Multiview

 Vulkan has introduced [`VK_KHR_multiview`](https://github.com/KhronosGroup/Vulkan-Docs/blob/master/appendices/VK_KHR_multiview.txt) in Vulkan 1.1 to facilitate the implementation of VR rendering. It allows user to index data with `gl_ViewIndex` and output it to the corresponding layer of the attachment image view. 

In my use case, I have encountered a situation while implementing PBR pipeline where I need to render HDR map and radiance map to cube maps. Each face of the cube map is generated with a camera placed orthogonally to each other. 

## Enable Extensions

There are extensions we need to enable on the logical device and on the instance. 

Logical: `VK_KHR_MULTIVIEW_EXTENSION_NAME`,  

Instance: `VK_KHR_get_physical_device_properties2`

## Fill Multiview Create Info Struct

Multiview usage is declared while creating render pass. To tell the render pass to use mutliview, simply 
fill a multiview create info `VkRenderPassMultiviewCreateInfo`,  and put it to the `pNext` of the renderpass create info

```c++
    VkRenderPassMultiviewCreateInfo multiViewCI = {};
    multiViewCI.sType = VK_STRUCTURE_TYPE_RENDER_PASS_MULTIVIEW_CREATE_INFO;
    multiViewCI.subpassCount = viewMasks.size();
    multiViewCI.pViewMasks = viewMasks.data();
    
    VkRenderPassCreateInfo renderPassInfo = {};
    renderPassInfo.pNext = &multiViewCI;
    //... Other Renderpass Info...
```
## Create Image and Framebuffer to Take the output

Each view will write to the corresponding layer of the attachment of the framebuffer. So the Image of the attachment needs to be number of view layers. However, the framebuffer can have only 1 layer. It’s the attachment to have multiple layers. Here’s an explanation form the specification: [VkFramebufferCreateInfo](https://www.khronos.org/registry/vulkan/specs/1.2-extensions/man/html/VkFramebufferCreateInfo.html).
```c++
// This is my code to generate a image and view
// with 1 mip and 6 layers
VkImageView view = GetRenderResourceManager()
    ->getColorTarget("irr_cube_map", {IRR_CUBE_DIM, IRR_CUBE_DIM},
                     TEX_FORMAT, 1, 6) // <- 1 mip, 6 layers
                     ->getView();
// Create framebuffer
VkFramebufferCreateInfo frameBufferCreateInfo = {};
frameBufferCreateInfo.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO;
frameBufferCreateInfo.layers = 1; // <- 1 layer for framebuffer
frameBufferCreateInfo.pAttachments = &view;
// ... other framebuffer info
```

## Enable Shader Extension and Use the View Index

The only change I made is in the vertex shader to index ProjectView matrix with `gl_ViewIndex`.
```glsl
#extension GL_EXT_multiview : enable // <- Enable shader extension
// Hardcoded mPV for each face of the cube
mat4 mProjViews[6] = {{{0.000000, 0.000000, 1.010101, 1.000000},
                       {0.000000, -1.000000, 0.000000, 0.000000},
                       {-1.000000, 0.000000, 0.000000, 0.000000},
                       {0.000000, 0.000000, -0.101010, 0.000000}},
                      {{0.000000, 0.000000, -1.010101, -1.000000},
                       {0.000000, -1.000000, 0.000000, 0.000000},
                       {1.000000, 0.000000, 0.000000, 0.000000},
                       {0.000000, 0.000000, -0.101010, 0.000000}},
                      {{1.000000, 0.000000, 0.000000, 0.000000},
                       {0.000000, 0.000000, 1.010101, 1.000000},
                       {0.000000, 1.000000, 0.000000, 0.000000},
                       {0.000000, 0.000000, -0.101010, 0.000000}},
                      {{1.000000, 0.000000, 0.000000, 0.000000},
                       {0.000000, 0.000000, -1.010101, -1.000000},
                       {0.000000, -1.000000, 0.000000, 0.000000},
                       {0.000000, 0.000000, -0.101010, 0.000000}},
                      {{1.000000, 0.000000, 0.000000, 0.000000},
                       {0.000000, -1.000000, 0.000000, 0.000000},
                       {0.000000, 0.000000, 1.010101, 1.000000},
                       {0.000000, 0.000000, -0.101010, 0.000000}},
                      {{-1.000000, 0.000000, 0.000000, 0.000000},
                       {0.000000, -1.000000, 0.000000, 0.000000},
                       {0.000000, 0.000000, -1.010101, -1.000000},
                       {0.000000, 0.000000, -0.101010, 0.000000}}};
// Indexing the output
gl_Position = mProjViews[gl_ViewIndex] * vec4(inPos, 1.0);
```
Don't forget to enable shader extension: `#extension GL_EXT_multiview : enable`.

## Implementations note

* Mutliview is not supported by MacOS with MoltenVK, track the feature [at Github issue](https://github.com/KhronosGroup/MoltenVK/issues/347).
* Skybox need to change front face mode since we are looking from the inside. This applies if you are using a cube mesh like I do.
* glm need to force the range between 0, 1 using macro: `#defineGLM_FORCE_DEPTH_ZERO_TO_ONE`

## Bonus: Code to generate cube views
Here's the code I used to generate the hard coded View matrices used in the shader above to look at 6 faces of the cube.
```c++
#define GLM_ENABLE_EXPERIMENTAL
#define GLM_FORCE_DEPTH_ZERO_TO_ONE
#include "glm/glm.hpp"
#include "glm/glm/gtc/matrix_transform.hpp"
#include "glm/glm/gtx/string_cast.hpp"
#include <iostream>

int main()
{
    glm::mat4 captureProjection =
        glm::perspective((float)M_PI / 2.0f, 1.0f, 0.1f, 10.0f);
    glm::mat4 captureViews[] = {
        glm::lookAt(glm::vec3(0.0f, 0.0f, 0.0f), glm::vec3(1.0f, 0.0f, 0.0f),
                    glm::vec3(0.0f, -1.0f, 0.0f)),
        glm::lookAt(glm::vec3(0.0f, 0.0f, 0.0f), glm::vec3(-1.0f, 0.0f, 0.0f),
                    glm::vec3(0.0f, -1.0f, 0.0f)),
        glm::lookAt(glm::vec3(0.0f, 0.0f, 0.0f), glm::vec3(0.0f, 1.0f, 0.0f),
                    glm::vec3(0.0f, 0.0f, 1.0f)),
        glm::lookAt(glm::vec3(0.0f, 0.0f, 0.0f), glm::vec3(0.0f, -1.0f, 0.0f),
                    glm::vec3(0.0f, 0.0f, -1.0f)),
        glm::lookAt(glm::vec3(0.0f, 0.0f, 0.0f), glm::vec3(0.0f, 0.0f, 1.0f),
                    glm::vec3(0.0f, -1.0f, 0.0f)),
        glm::lookAt(glm::vec3(0.0f, 0.0f, 0.0f), glm::vec3(0.0f, 0.0f, -1.0f),
                    glm::vec3(0.0f, -1.0f, 0.0f))};

    for (int i = 0; i<6; i++)
    {
        std::cout<<glm::to_string(captureProjection * captureViews[i])<<std::endl;
    }
    return 0;
}
```

