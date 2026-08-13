import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { VRMHumanBoneName } from "@pixiv/three-vrm";

import {
  createIrisTargetBindRotations,
  createProceduralIdlePose,
  retargetMixamoPose,
} from "./avatar-retarget";

describe("Mixamo to normalized VRM retargeting", () => {
  it("uses the first animated frame as a zero-motion reference", () => {
    const bone = new THREE.Object3D();
    bone.quaternion.setFromEuler(new THREE.Euler(0.2, -0.4, 0.1));
    bone.position.set(3, 100, -2);
    const reference = new Map([["mixamorigHips", {
      quaternion: bone.quaternion.clone(),
      position: bone.position.clone(),
    }]]);
    const result = retargetMixamoPose(
      new Map([["mixamorigHips", bone]]),
      reference,
      new Map(),
      new Map([[VRMHumanBoneName.Hips, new THREE.Vector3(0, 0.862, 0)]]),
    );

    expect(result.rotations.get(VRMHumanBoneName.Hips)).toEqual(new THREE.Quaternion());
    expect(result.hipsPosition.toArray()).toEqual([0, 0.862, 0]);
  });

  it("keeps imported arm chains on the authored Iris bind frame", () => {
    const referenceQuaternion = new THREE.Quaternion();
    const source = new THREE.Object3D();
    source.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 4);
    const bind = createIrisTargetBindRotations();
    const result = retargetMixamoPose(
      new Map([["mixamorigLeftArm", source]]),
      new Map([["mixamorigLeftArm", { position: new THREE.Vector3(), quaternion: referenceQuaternion }]]),
      bind,
      new Map(),
    );
    expect(result.rotations.get(VRMHumanBoneName.LeftUpperArm)!.angleTo(bind.get(VRMHumanBoneName.LeftUpperArm)!)).toBeLessThan(0.00001);
  });

  it("does not allow extreme Mixamo arm or wrist rotations to change Iris's pose", () => {
    const source = new THREE.Object3D();
    source.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI);
    const bind = createIrisTargetBindRotations();
    const result = retargetMixamoPose(
      new Map([
        ["mixamorigLeftArm", source],
        ["mixamorigLeftHand", source],
      ]),
      new Map([
        ["mixamorigLeftArm", { position: new THREE.Vector3(), quaternion: new THREE.Quaternion() }],
        ["mixamorigLeftHand", { position: new THREE.Vector3(), quaternion: new THREE.Quaternion() }],
      ]),
      bind,
      new Map(),
    );

    expect(result.rotations.get(VRMHumanBoneName.LeftUpperArm)!.angleTo(bind.get(VRMHumanBoneName.LeftUpperArm)!)).toBeLessThan(0.00001);
    expect(result.rotations.get(VRMHumanBoneName.LeftHand)!.angleTo(new THREE.Quaternion())).toBeLessThan(0.00001);
  });

  it("keeps the procedural neutral idle on the authored bind frame", () => {
    const bind = createIrisTargetBindRotations();
    const rest = new Map([[VRMHumanBoneName.Hips, new THREE.Vector3(0, 0.862, 0)]]);
    const pose = createProceduralIdlePose("neutral", 0, bind, rest);

    expect(pose.hipsPosition.toArray()).toEqual([0, 0.862, 0]);
    expect(pose.rotations.get(VRMHumanBoneName.LeftUpperArm)!.angleTo(bind.get(VRMHumanBoneName.LeftUpperArm)!)).toBeLessThan(0.00001);
    expect(pose.rotations.get(VRMHumanBoneName.RightUpperArm)!.angleTo(bind.get(VRMHumanBoneName.RightUpperArm)!)).toBeLessThan(0.00001);
  });

  it("keeps every procedural idle at its authored pose when its loop closes", () => {
    const bind = createIrisTargetBindRotations();
    const rest = new Map([[VRMHumanBoneName.Hips, new THREE.Vector3(0, 0.862, 0)]]);
    const durations = { neutral: 18, "weight-shift": 9, "look-around": 7, refocus: 6.5 } as const;

    for (const [kind, duration] of Object.entries(durations) as [keyof typeof durations, number][]) {
      const start = createProceduralIdlePose(kind, 0, bind, rest, 1.7);
      const end = createProceduralIdlePose(kind, duration, bind, rest, 1.7);
      expect(end.hipsPosition.distanceTo(start.hipsPosition)).toBeLessThan(0.00001);
      expect(end.rotations.get(VRMHumanBoneName.Head)!.angleTo(start.rotations.get(VRMHumanBoneName.Head)!)).toBeLessThan(0.00001);
      expect(end.rotations.get(VRMHumanBoneName.Chest)!.angleTo(start.rotations.get(VRMHumanBoneName.Chest)!)).toBeLessThan(0.00001);
    }
  });
});
