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

  it("maps a source delta onto the same target bind frame", () => {
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
    const expected = source.quaternion.clone().multiply(bind.get(VRMHumanBoneName.LeftUpperArm)!).normalize();
    expect(result.rotations.get(VRMHumanBoneName.LeftUpperArm)!.angleTo(expected)).toBeLessThan(0.00001);
  });

  it("keeps the procedural neutral idle on the authored bind frame", () => {
    const bind = createIrisTargetBindRotations();
    const rest = new Map([[VRMHumanBoneName.Hips, new THREE.Vector3(0, 0.862, 0)]]);
    const pose = createProceduralIdlePose("neutral", 0, bind, rest);

    expect(pose.hipsPosition.toArray()).toEqual([0, 0.862, 0]);
    expect(pose.rotations.get(VRMHumanBoneName.LeftUpperArm)!.angleTo(bind.get(VRMHumanBoneName.LeftUpperArm)!)).toBeLessThan(0.00001);
    expect(pose.rotations.get(VRMHumanBoneName.RightUpperArm)!.angleTo(bind.get(VRMHumanBoneName.RightUpperArm)!)).toBeLessThan(0.00001);
  });
});
