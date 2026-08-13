import * as THREE from "three";
import { VRMHumanBoneName } from "@pixiv/three-vrm";

export type SourceBoneReference = {
  position: THREE.Vector3;
  quaternion: THREE.Quaternion;
};

export type RetargetedPose = {
  rotations: Map<VRMHumanBoneName, THREE.Quaternion>;
  hipsPosition: THREE.Vector3;
};

export type ProceduralIdleKind = "neutral" | "weight-shift" | "look-around" | "refocus";

/** Mixamo's humanoid names mapped to the VRM humanoid contract. */
export const MIXAMO_BONE_MAP: readonly (readonly [VRMHumanBoneName, string])[] = [
  [VRMHumanBoneName.Hips, "mixamorigHips"],
  [VRMHumanBoneName.Spine, "mixamorigSpine"],
  [VRMHumanBoneName.Chest, "mixamorigSpine1"],
  [VRMHumanBoneName.UpperChest, "mixamorigSpine2"],
  [VRMHumanBoneName.Neck, "mixamorigNeck"],
  [VRMHumanBoneName.Head, "mixamorigHead"],
  [VRMHumanBoneName.LeftShoulder, "mixamorigLeftShoulder"],
  [VRMHumanBoneName.LeftUpperArm, "mixamorigLeftArm"],
  [VRMHumanBoneName.LeftLowerArm, "mixamorigLeftForeArm"],
  [VRMHumanBoneName.LeftHand, "mixamorigLeftHand"],
  [VRMHumanBoneName.RightShoulder, "mixamorigRightShoulder"],
  [VRMHumanBoneName.RightUpperArm, "mixamorigRightArm"],
  [VRMHumanBoneName.RightLowerArm, "mixamorigRightForeArm"],
  [VRMHumanBoneName.RightHand, "mixamorigRightHand"],
  [VRMHumanBoneName.LeftUpperLeg, "mixamorigLeftUpLeg"],
  [VRMHumanBoneName.LeftLowerLeg, "mixamorigLeftLeg"],
  [VRMHumanBoneName.LeftFoot, "mixamorigLeftFoot"],
  [VRMHumanBoneName.LeftToes, "mixamorigLeftToeBase"],
  [VRMHumanBoneName.RightUpperLeg, "mixamorigRightUpLeg"],
  [VRMHumanBoneName.RightLowerLeg, "mixamorigRightLeg"],
  [VRMHumanBoneName.RightFoot, "mixamorigRightFoot"],
  [VRMHumanBoneName.RightToes, "mixamorigRightToeBase"],
];

const MIXAMO_TRANSLATION_SCALE = 0.01;

const UNSAFE_MIXAMO_ARM_BONES = new Set<VRMHumanBoneName>([
  VRMHumanBoneName.LeftShoulder,
  VRMHumanBoneName.LeftUpperArm,
  VRMHumanBoneName.LeftLowerArm,
  VRMHumanBoneName.LeftHand,
  VRMHumanBoneName.RightShoulder,
  VRMHumanBoneName.RightUpperArm,
  VRMHumanBoneName.RightLowerArm,
  VRMHumanBoneName.RightHand,
]);

/**
 * The VRM normalized rig is a canonical T-pose. Iris is authored to enter in
 * a relaxed A-pose, so the target bind frame is part of the rig profile. It
 * is applied identically to every clip; it is not a per-animation patch.
 */
export function createIrisTargetBindRotations(): Map<VRMHumanBoneName, THREE.Quaternion> {
  const rotations = new Map<VRMHumanBoneName, THREE.Quaternion>();
  const entries: readonly (readonly [VRMHumanBoneName, number])[] = [
    [VRMHumanBoneName.LeftUpperArm, THREE.MathUtils.degToRad(77.4)],
    [VRMHumanBoneName.RightUpperArm, THREE.MathUtils.degToRad(-77.4)],
    [VRMHumanBoneName.LeftLowerArm, THREE.MathUtils.degToRad(-21.6)],
    [VRMHumanBoneName.RightLowerArm, THREE.MathUtils.degToRad(21.6)],
  ];
  for (const [bone, angle] of entries) {
    rotations.set(bone, new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), angle));
  }
  return rotations;
}

/**
 * Converts one sampled Mixamo pose into Iris's normalized VRM pose.
 *
 * The reference is the first animated frame, not the FBX bind pose. Mixamo
 * animation-only exports commonly have a different bind frame from their
 * first keyframe; subtracting the FBX bind pose would otherwise introduce a
 * T-pose on entry. The target bind rotation is then applied uniformly to the
 * source delta. Iris and Mixamo use incompatible arm-axis conventions, so
 * imported clips intentionally do not control the arm chains: their authored
 * A-pose remains fixed and cannot twist through the body. Author-controlled
 * idle movement still adds a small, safe arm sway independently.
 */
export function retargetMixamoPose(
  bones: ReadonlyMap<string, THREE.Object3D>,
  references: ReadonlyMap<string, SourceBoneReference>,
  targetRestRotations: ReadonlyMap<VRMHumanBoneName, THREE.Quaternion>,
  targetRestPositions: ReadonlyMap<VRMHumanBoneName, THREE.Vector3>,
): RetargetedPose {
  const rotations = new Map<VRMHumanBoneName, THREE.Quaternion>();
  const hipsPosition = targetRestPositions.get(VRMHumanBoneName.Hips)?.clone() ?? new THREE.Vector3();

  for (const [humanBone, mixamoName] of MIXAMO_BONE_MAP) {
    const source = bones.get(mixamoName);
    const reference = references.get(mixamoName);
    if (!source || !reference) continue;

    const targetBind = targetRestRotations.get(humanBone) ?? new THREE.Quaternion();
    if (UNSAFE_MIXAMO_ARM_BONES.has(humanBone)) {
      rotations.set(humanBone, targetBind.clone());
      continue;
    }
    const sourceDelta = source.quaternion.clone()
      .multiply(reference.quaternion.clone().invert())
      .normalize();
    rotations.set(humanBone, sourceDelta.multiply(targetBind).normalize());

    if (humanBone === VRMHumanBoneName.Hips) {
      hipsPosition.add(source.position.clone().sub(reference.position).multiplyScalar(MIXAMO_TRANSLATION_SCALE));
    }
  }

  return { rotations, hipsPosition };
}

function addLocalRotation(
  rotations: Map<VRMHumanBoneName, THREE.Quaternion>,
  humanBone: VRMHumanBoneName,
  targetBindRotations: ReadonlyMap<VRMHumanBoneName, THREE.Quaternion>,
  x = 0,
  y = 0,
  z = 0,
): void {
  const base = targetBindRotations.get(humanBone)?.clone() ?? new THREE.Quaternion();
  rotations.set(
    humanBone,
    new THREE.Quaternion().setFromEuler(new THREE.Euler(x, y, z)).multiply(base).normalize(),
  );
}

/**
 * Author-controlled idle motion for Iris's normalized rig.
 *
 * The old neutral FBX was an animation-only export whose authored pose was a
 * poor match for Iris. These idles keep the same retargeted VRM contract as
 * gestures, but their neutral pose and movement amplitudes are explicit and
 * stable: breathing moves the torso, weight shift moves the hips and chest,
 * and look-around turns the neck and upper body together.
 */
export function createProceduralIdlePose(
  kind: ProceduralIdleKind,
  timeSeconds: number,
  targetBindRotations: ReadonlyMap<VRMHumanBoneName, THREE.Quaternion>,
  targetRestPositions: ReadonlyMap<VRMHumanBoneName, THREE.Vector3>,
  variation = 0,
): RetargetedPose {
  const rotations = new Map<VRMHumanBoneName, THREE.Quaternion>();
  for (const humanBone of Object.values(VRMHumanBoneName) as VRMHumanBoneName[]) {
    addLocalRotation(rotations, humanBone, targetBindRotations);
  }

  const durations: Record<ProceduralIdleKind, number> = {
    neutral: 18,
    "weight-shift": 9,
    "look-around": 7,
    refocus: 6.5,
  };
  const phase = (timeSeconds / durations[kind]) * Math.PI * 2;
  // Every term evaluates to zero at both ends of the loop. That lets a new
  // seeded variation begin from the authored neutral pose without a seam.
  const wave = Math.sin(phase + variation) - Math.sin(variation);
  const slowWave = Math.sin(phase + variation * 0.67) - Math.sin(variation * 0.67);
  const detailWave = Math.sin(phase * 2 + variation * 1.31) - Math.sin(variation * 1.31);
  const hipsPosition = targetRestPositions.get(VRMHumanBoneName.Hips)?.clone() ?? new THREE.Vector3();

  if (kind === "neutral") {
    hipsPosition.y += wave * 0.006 + detailWave * 0.0015;
    addLocalRotation(rotations, VRMHumanBoneName.Hips, targetBindRotations, wave * 0.009, slowWave * 0.01, 0);
    addLocalRotation(rotations, VRMHumanBoneName.Spine, targetBindRotations, wave * 0.021, 0, slowWave * 0.01);
    addLocalRotation(rotations, VRMHumanBoneName.Chest, targetBindRotations, wave * 0.031, 0, slowWave * 0.013);
    addLocalRotation(rotations, VRMHumanBoneName.UpperChest, targetBindRotations, wave * 0.022, 0, slowWave * 0.01);
    addLocalRotation(rotations, VRMHumanBoneName.Neck, targetBindRotations, slowWave * 0.013, wave * 0.021, 0);
    addLocalRotation(rotations, VRMHumanBoneName.Head, targetBindRotations, wave * 0.008, slowWave * 0.018, 0);
    addLocalRotation(rotations, VRMHumanBoneName.LeftUpperArm, targetBindRotations, 0, 0, wave * 0.029);
    addLocalRotation(rotations, VRMHumanBoneName.RightUpperArm, targetBindRotations, 0, 0, -wave * 0.029);
    addLocalRotation(rotations, VRMHumanBoneName.LeftLowerArm, targetBindRotations, 0, 0, -wave * 0.017);
    addLocalRotation(rotations, VRMHumanBoneName.RightLowerArm, targetBindRotations, 0, 0, wave * 0.017);
  } else if (kind === "weight-shift") {
    hipsPosition.x += wave * 0.035;
    hipsPosition.y += Math.abs(wave) * 0.004;
    addLocalRotation(rotations, VRMHumanBoneName.Hips, targetBindRotations, wave * 0.016, 0, wave * 0.07);
    addLocalRotation(rotations, VRMHumanBoneName.Spine, targetBindRotations, 0, 0, -wave * 0.045);
    addLocalRotation(rotations, VRMHumanBoneName.Chest, targetBindRotations, 0, 0, -wave * 0.06);
    addLocalRotation(rotations, VRMHumanBoneName.UpperChest, targetBindRotations, 0, 0, -wave * 0.04);
    addLocalRotation(rotations, VRMHumanBoneName.Neck, targetBindRotations, 0, 0, -wave * 0.024);
    addLocalRotation(rotations, VRMHumanBoneName.Head, targetBindRotations, 0, 0, -wave * 0.024);
    addLocalRotation(rotations, VRMHumanBoneName.LeftUpperArm, targetBindRotations, 0, 0, wave * 0.08);
    addLocalRotation(rotations, VRMHumanBoneName.RightUpperArm, targetBindRotations, 0, 0, -wave * 0.08);
    addLocalRotation(rotations, VRMHumanBoneName.LeftLowerArm, targetBindRotations, 0, 0, -wave * 0.044);
    addLocalRotation(rotations, VRMHumanBoneName.RightLowerArm, targetBindRotations, 0, 0, wave * 0.044);
  } else {
    if (kind === "look-around") {
      hipsPosition.x += slowWave * 0.006;
      addLocalRotation(rotations, VRMHumanBoneName.Hips, targetBindRotations, 0, slowWave * 0.01, slowWave * 0.006);
      addLocalRotation(rotations, VRMHumanBoneName.Spine, targetBindRotations, 0, wave * 0.01, 0);
      addLocalRotation(rotations, VRMHumanBoneName.Chest, targetBindRotations, 0, wave * 0.021, 0);
      addLocalRotation(rotations, VRMHumanBoneName.UpperChest, targetBindRotations, 0, wave * 0.031, 0);
      addLocalRotation(rotations, VRMHumanBoneName.Neck, targetBindRotations, 0, wave * 0.061, slowWave * 0.011);
      addLocalRotation(rotations, VRMHumanBoneName.Head, targetBindRotations, slowWave * 0.008, wave * 0.105, slowWave * 0.016);
      addLocalRotation(rotations, VRMHumanBoneName.LeftUpperArm, targetBindRotations, 0, 0, slowWave * 0.019);
      addLocalRotation(rotations, VRMHumanBoneName.RightUpperArm, targetBindRotations, 0, 0, -slowWave * 0.019);
    } else {
      // A short, contained refocus: the eyes/head acknowledge something,
      // then the full torso settles back. It is deliberately quieter than a
      // gesture and only the scheduler may choose it.
      const settle = 1 - Math.cos(phase);
      addLocalRotation(rotations, VRMHumanBoneName.Hips, targetBindRotations, settle * 0.006, 0, settle * 0.01);
      addLocalRotation(rotations, VRMHumanBoneName.Spine, targetBindRotations, settle * 0.01, wave * 0.013, -settle * 0.009);
      addLocalRotation(rotations, VRMHumanBoneName.Chest, targetBindRotations, settle * 0.016, wave * 0.024, -settle * 0.014);
      addLocalRotation(rotations, VRMHumanBoneName.Neck, targetBindRotations, settle * 0.012, wave * 0.048, 0);
      addLocalRotation(rotations, VRMHumanBoneName.Head, targetBindRotations, settle * 0.017, wave * 0.071, 0);
    }
  }

  return { rotations, hipsPosition };
}
