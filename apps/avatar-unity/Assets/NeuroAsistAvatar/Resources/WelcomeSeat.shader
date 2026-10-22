Shader "Iris/WelcomeSeat"
{
    Properties { _Color ("Graphite", Color) = (.25, .25, .29, 1) }
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        LOD 150
        CGPROGRAM
        #pragma surface surf Lambert
        struct Input { float2 uv_MainTex; };
        fixed4 _Color;
        void surf(Input IN, inout SurfaceOutput o) { o.Albedo = _Color.rgb; o.Emission = _Color.rgb * .28; o.Alpha = 1; }
        ENDCG
    }
    Fallback "Diffuse"
}
