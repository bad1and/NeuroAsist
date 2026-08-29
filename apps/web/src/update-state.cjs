const fs = require('fs');
let code = fs.readFileSync('state.tsx', 'utf8');

const imports = import { Metaballs } from '@paper-design/shaders-react';
import { getMoodVisuals, getStrengthLabel } from './mood-visuals';
;

code = code.replace('import { IconInterfaceSpirals', imports + 'import { IconInterfaceSpirals');

const moodVisualOld = <div className="mood-visual">
                  <div className="mood-orb" data-emotion={state.mood.primary_emotion?.toLowerCase() || "neutral"} />
                  <div className="mood-info">
                    <h2>{state.mood.primary_emotion}</h2>
                    <span className="mood-strength">{state.mood.expression_strength}</span>
                  </div>
                </div>;

const moodVisualNew = 
                <div className="mood-visual" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div className="mood-metaball-container" style={{ width: 64, height: 64, borderRadius: '50%', overflow: 'hidden', flexShrink: 0, position: 'relative' }}>
                    {(() => {
                      const visuals = getMoodVisuals(state.mood.primary_emotion);
                      return (
                        <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }}>
                          <Metaballs
                            width={160}
                            height={160}
                            colors={visuals.colors}
                            colorBack="transparent"
                            count={12}
                            size={1.2}
                            speed={visuals.speed}
                            scale={0.6}
                          />
                        </div>
                      );
                    })()}
                  </div>
                  <div className="mood-info">
                    <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>{getMoodVisuals(state.mood.primary_emotion).labelRu}</h2>
                    <span className="mood-strength" style={{ color: 'var(--color-text-muted)', fontSize: '13px' }}>{getStrengthLabel(state.mood.expression_strength)}</span>
                  </div>
                </div>;

code = code.replace(moodVisualOld, moodVisualNew);
fs.writeFileSync('state.tsx', code, 'utf8');
