const fs = require('fs');
let code = fs.readFileSync('state.tsx', 'utf8');

const oldVisual = <div className="mood-visual" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div className="mood-metaball-container" style={{ width: 64, height: 64, flexShrink: 0, position: 'relative' }}>
                    {(() => {
                      const visuals = getMoodVisuals(state.mood.primary_emotion);
                      return (
                        <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', width: 120, height: 120 }}>
                          <Metaballs
                            width={120}
                            height={120}
                            colors={visuals.colors}
                            colorBack="transparent"
                            count={15}
                            size={1.5}
                            speed={visuals.speed}
                            scale={0.6}
                          />
                        </div>
                      );
                    })()}
                  </div>
                  <div className="mood-info">
                    <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>{getMoodVisuals(state.mood.primary_emotion).labelRu}</h2>
                    <span className="mood-strength" style={{ color: 'var(--color-text-muted, #888)', fontSize: '13px' }}>{getStrengthLabel(state.mood.expression_strength)}</span>
                  </div>
                </div>;

const newVisual = 
                <div className="mood-visual" style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <div className="mood-metaball-container" style={{ width: 64, height: 64, flexShrink: 0, position: 'relative' }}>
                    {(() => {
                      const visuals = getMoodVisuals(state.mood.primary_emotion);
                      return (
                        <div style={{ 
                          position: 'absolute', 
                          top: '50%', 
                          left: '50%', 
                          transform: 'translate(-50%, -50%)', 
                          width: 100, 
                          height: 100, 
                          WebkitMaskImage: 'radial-gradient(circle, white 35%, transparent 65%)', 
                          maskImage: 'radial-gradient(circle, white 35%, transparent 65%)' 
                        }}>
                          <Metaballs
                            width={100}
                            height={100}
                            colors={visuals.colors}
                            colorBack="#1c1d21"
                            count={15}
                            size={1.3}
                            speed={visuals.speed}
                            scale={0.6}
                          />
                        </div>
                      );
                    })()}
                  </div>
                  <div className="mood-info" style={{ zIndex: 1 }}>
                    <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>{getMoodVisuals(state.mood.primary_emotion).labelRu}</h2>
                    <span className="mood-strength" style={{ color: 'var(--color-text-muted, #888)', fontSize: '13px' }}>{getStrengthLabel(state.mood.expression_strength)}</span>
                  </div>
                </div>;

code = code.replace(oldVisual, newVisual);
fs.writeFileSync('state.tsx', code, 'utf8');
