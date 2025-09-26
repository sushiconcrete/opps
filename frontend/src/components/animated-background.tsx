"use client"

import { Dithering } from "@paper-design/shaders-react"

export function AnimatedBackground() {
  return (
    <div className="fixed inset-0 -z-10">
      <Dithering
        colorBack="#080808"
        colorFront="#808080"
        speed={0.5}
        shape="wave"
        type="4x4"
        pxSize={1.9}
        scale={-3}
        style={{ width: "100vw", height: "100vh", opacity: 0.3}}
      />
    </div>
  )
}
