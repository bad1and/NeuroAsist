const fs = require('fs');
let code = fs.readFileSync('state.tsx', 'utf8');

const oldVisual = <div style={{ 
                          position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%) scale(0.15)', 
                          width: 1280, height: 720,
                          mixBlendMode: 'screen',
                          pointerEvents: 'none'
                        }}>
                          <Metaballs
                            width={1280}
                            height={720}
                            colors={visuals.colors}
                            colorBack="#000000"
                            count={20}
                            size={1}
                            speed={visuals.speed}
                            scale={0.64}
                          />
                        </div>;

const newVisual = <div style={{ 
                          position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%) scale(0.22)', 
                          width: 1280, height: 720,
                          pointerEvents: 'none',
                          WebkitMaskImage: 'radial-gradient(circle at center, white 250px, transparent 350px)',
                          maskImage: 'radial-gradient(circle at center, white 250px, transparent 350px)'
                        }}>
                          <Metaballs
                            width={1280}
                            height={720}
                            colors={visuals.colors}
                            colorBack="#232429"
                            count={20}
                            size={1}
                            speed={visuals.speed}
                            scale={0.64}
                          />
                        </div>;

code = code.replace(oldVisual, newVisual);
fs.writeFileSync('state.tsx', code, 'utf8');
