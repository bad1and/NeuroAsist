Shader "Hidden/Iris/AvatarEdgeFeather"
{
    Properties { _MainTex ("Portrait", 2D) = "black" {} }
    SubShader
    {
        Cull Off ZWrite Off ZTest Always
        Pass
        {
            CGPROGRAM
            #pragma vertex vert_img
            #pragma fragment frag
            #pragma target 3.0
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            float4 _MainTex_TexelSize;

            float4 ToDesktopAlpha(float4 colour)
            {
                float alpha = saturate(colour.a);
                if (alpha <= 0.00001) return 0;
                #ifndef UNITY_COLORSPACE_GAMMA
                    // DWM composites premultiplied display RGB. Unity renders in
                    // linear light: premultiply after encoding, then undo that
                    // encoding for Unity's final sRGB write to the swapchain.
                    float3 straight = max(0, colour.rgb / alpha);
                    float3 display = float3(LinearToGammaSpaceExact(straight.r),
                        LinearToGammaSpaceExact(straight.g), LinearToGammaSpaceExact(straight.b)) * alpha;
                    colour.rgb = float3(GammaToLinearSpaceExact(display.r),
                        GammaToLinearSpaceExact(display.g), GammaToLinearSpaceExact(display.b));
                #endif
                return float4(colour.rgb, alpha);
            }

            float4 frag(v2f_img input) : SV_Target
            {
                float2 size = _MainTex_TexelSize.zw;
                float2 pixel = input.uv * size;
                // Scale with portrait height, including host scale and Windows DPI.
                // There is deliberately no bottom mask: Iris still meets the dock.
                float sideWidth = min(size.x * 0.14, size.y * (36.0 / 520.0));
                float topWidth = min(size.y * 0.08, size.y * (20.0 / 520.0));
                float sideDistance = min(pixel.x, size.x - pixel.x);
                float topDistance = (1.0 - input.uv.y) * size.y;
                float visibility = smoothstep(1.5, max(2.5, sideWidth), sideDistance)
                    * smoothstep(1.5, max(2.5, topWidth), topDistance);
                // Ease into the feather more gently, retaining more of the
                // original colour instead of making the edge read as a shadow.
                visibility = 1.0 - pow(1.0 - visibility, 1.5);
                float4 original = tex2D(_MainTex, input.uv);
                if (visibility >= 0.99999) return ToDesktopAlpha(original);
                if (visibility <= 0.0) return 0;

                // A small, local nine-tap blur. The untouched centre takes one tap.
                float2 radius = abs(_MainTex_TexelSize.xy)
                    * min(3.0, size.y * (2.0 / 520.0)) * (1.0 - visibility);
                float4 blurred = original * 0.25;
                blurred += tex2D(_MainTex, input.uv + float2(radius.x, 0)) * 0.125;
                blurred += tex2D(_MainTex, input.uv - float2(radius.x, 0)) * 0.125;
                blurred += tex2D(_MainTex, input.uv + float2(0, radius.y)) * 0.125;
                blurred += tex2D(_MainTex, input.uv - float2(0, radius.y)) * 0.125;
                blurred += tex2D(_MainTex, input.uv + radius) * 0.0625;
                blurred += tex2D(_MainTex, input.uv - radius) * 0.0625;
                blurred += tex2D(_MainTex, input.uv + float2(radius.x, -radius.y)) * 0.0625;
                blurred += tex2D(_MainTex, input.uv + float2(-radius.x, radius.y)) * 0.0625;
                // Fade coverage, never blend hair with a fixed dark background.
                return ToDesktopAlpha(blurred * visibility);
            }
            ENDCG
        }
    }
    Fallback Off
}
