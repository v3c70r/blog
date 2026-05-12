---
title: Oblique Plane in Clip Space with Z in [0, 1.0] and reversed Z
slug: oblique-clipping-plane
date: 2020-10-30 02:00
lang: en
category: graphics
tags: graphics, rendering, clipping plane
author: Qing Gu
summary: Using oblique clipping plane in Vulkan and D3D clip space.
mathjax: true
---

Oblique clipping plane in frustum can be used to cull primitives with arbitrary plane. It's especially useful in rasterizing mirrors. 
[The paper by Eric Lengyel](http://www.terathon.com/lengyel/Lengyel-Oblique.pdf) has discussed the derivation of such clipping plane in OpenGL NDC with $x, y, z \in [-1.0, 1.0]$. However in other APIs like D3D and Vulkan, the z lies in $z\in[0.0, 1.0]$ . This article discusses how we modify the original method proposed in the paper to achieve the same result.

In addition, we'll talk about how to handle the matrix with reversed Z techniques. 

In the following discussion, elements with *prime(')* are in view space, otherwise, they are in clip space. There are the notations we used in the following discussion:

* $C_n$: Near clipping plane in clip space, $C_n'$ is the clipping plane in view space.
* $C_f$: Far clipping plane in clip space, $C_f'$ is the far clipping plane in view space.
* $M$: Projection matrix where $M_n$  denotes the *n*th row , i.e.:

$$M = \begin{pmatrix}
M_1\\ 
M_2\\ 
M_3\\ 
M_4
\end{pmatrix}$$
* $Q$ denotes a point opposite to the near clipping plane. We'll discuss it later.

## Oblique Clipping Plane

> TL;DR
>
> Substitute the third row of projection $M_3$ with 
> $$M_3=\frac{M_4\cdot Q'}{C_n \cdot Q'}C_n'$$
> where $Q' = M^{-1}Q$ and $Q=(sgn({C_n}_x), sgn({C_n}_y), 1, 1))$

Giving a normal $\mathbf{n}$ and a point $\mathbf{p}$, we can construct a plane $C=<\mathbf{n}_x, \mathbf{n}_y, \mathbf{n}_z, -\mathbf{n}\cdot \mathbf{p}$>.
Also, to transform a plane from view space to clip space, we need to apply the transpose of inverse of the matrix. 
$$C = (M^{-1})^TC'$$
This gives us the transformation of a plane from clip space to view space:
$$C' = M^TC$$
Picking a point $\mathbf{p_n}=(0, 0, 0)$ and normal $\mathbf{n_n}=(0, 0, 1)$on the near plane in clip space, we can have near clipping plane:
$$C_n=<0, 0, 1, 0>$$ 
The transformation of the plane from clip space to view space:
$$C_n' = M^TC_n=(M_1, M_2, M_3, M4)(0, 0, 1, 0)=M_3$$

Similarly, picking a point $\mathbf{p_f}=(0, 0, 1)$ and normal $\mathbf{n_f}=(0, 0, -1)$ on the far clipping plane, we have:
$$C_f=<0, 0, -1, 1>$$ 
$$C_f' = M^TC_f=M_4-M_3=M_4-C_n'$$
As discussed in the original paper, we want to find a scale factor $a$ that makes far plane $C'_f = M_4 - aC'_n$ crosses its opposite point $Q$ in the original clipp space, see the Q illustrated in the image.
![Q position](https://i.imgur.com/1hwILu2.png)
Then we can have the following equations:

$$
\left\{\begin{array}{ll}
Q'\cdot C_f'=0
\\
C'_f=M_4-C_n'
\\
Q'=M^{-1}Q
\\ 
Q=(sgn({C_n}_x), sgn({C_n}_y), 1, 1))
\end{array}\right.
$$

$$
\Rightarrow 
\left\{\begin{array}{ll}
a=\frac{M_4\cdot Q'}{C_n'\cdot Q'}C_n'
\\
Q'=M^{-1}Q
\\ 
Q=(sgn({C_n}_x), sgn({C_n}_y), 1, 1))
\\
M_3 = aC_n'
\end{array}\right.
$$

## A Note on Reversed Near Far Planes

It's not uncommon to use the [reversed Z trick](http://www.humus.name/index.php?page=Comments&ID=255&start=0) to gain more precision from the depth buffer to facilitate linear depth reconstruction. This trick simply swapped near and far planes in the projection matrix and use *GREATER* for depth test function.  However, this trick introduces complexity in the equations above. One easy way to handle this is to apply a Z flipping matrix $M_f$ after applying the oblique clipping plane, where:

$$M_f = \begin{bmatrix}
1 &  0&  0& 0\\ 
0 &  1&  0& 0\\ 
0 &  0&  -1& 1\\ 
0 &  0&  1& 1
\end{bmatrix}$$

## Further discussions on view space z reconstruction 

In the traditional projection matrix, depth can be reconstructed by simply knowing the depth at that pixel position, this is because the first two elements in the 3rd row($M_3$) are 0. When $w'=1$, depth remapping can be simply written as a function of clip space depth $z$:
$$z = \frac{M_{33}z'+M_{34}}{-z'}\rightarrow z'=\frac{M_{34}}{M_{33}+z}$$

However, when $M_{31}$ and $M_{32}$ are no longer 0, we'll need the clip space positions to reconstruct the depth. Given a point $\mathbf{p}(x, y, z, 1)$ in clip space, we can reconstruct the depth in view space $z'$:

$$
\left\{\begin{array}{ll}
x'=\frac{x}{M_{11}}
\\
y' = \frac{y}{M_{22}}
\\ 
z=\frac{\mathbf{M_3}\cdot \mathbf{p'}}{-z'}
\end{array}\right.
\Rightarrow z'=-\frac{\frac{M_{31}}{M_{11}}x+\frac{M_{32}}{M_{22}}y+M_{34}}{M_{33}+z}
$$
