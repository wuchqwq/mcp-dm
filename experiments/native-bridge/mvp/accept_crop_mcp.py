"""Explicit crop acceptance through real stdio MCP; never starts or closes DM.

NumPy is an independent oracle in this test client, not the native operator.
Run only after accepting the core backend, in the same prepared synthetic host.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
import numpy as np
from accept_mcp import StdioClient, ROOT, require, strict_json, validate_fixture, validate_receipt

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    parser.add_argument("--expected-host-pid", type=int, required=True)
    parser.add_argument("--rect", nargs=4, type=int, default=[2, 1, 8, 6])
    args = parser.parse_args()
    fixture = validate_fixture(strict_json(args.fixture.read_text(encoding="utf-8-sig")))
    source = fixture["images"][0]
    x0, y0, x1, y1 = args.rect
    require(0 <= x0 < x1 <= source["shape"][1] and 0 <= y0 < y1 <= source["shape"][0], "Invalid oracle ROI")
    original = np.load(source["source_npy"], allow_pickle=False)
    require(hashlib.sha256(original.tobytes()).hexdigest() == source["pixel_sha256"], "Fixture oracle changed")
    expected = original[y0:y1, x0:x1].copy()
    args.evidence_directory.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(DM_MCP_BACKEND="native", DM_NATIVE_SESSION=fixture["session"], DM_MCP_TIMEOUT_MS="5000")
    summary = {"status": "FAIL", "scope": "actual MCP crop plus native mean; full pixels independently verified in DM separately"}
    with (args.evidence_directory / "stdio-events.jsonl").open("x", encoding="utf-8") as trace:
        client = StdioClient([shutil.which("node") or "node", str(ROOT / "server.mjs")], env, trace)
        try:
            response = client.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "native-crop-acceptance", "version": "1"}})
            require("error" not in response, "Initialize failed")
            client.notify("notifications/initialized")
            catalog_response = client.rpc("tools/list", {})
            require("error" not in catalog_response, "tools/list failed")
            crop_tools = [tool for tool in catalog_response["result"].get("tools", []) if tool.get("name") == "dm_crop"]
            require(len(crop_tools) == 1 and "request_id" in crop_tools[0].get("inputSchema", {}).get("required", []),
                    "Native crop must require a caller-saved request_id")
            status_id = "crop-status-" + uuid.uuid4().hex
            status = client.tool("dm_status", {"request_id": status_id})
            validate_receipt(status, status_id, fixture["session"], "digitalmicrograph-native", args.expected_host_pid)
            require(status["ready"] is True and status["binary_gate"] is True, "Native adapter not ready")
            request_id = "crop-" + uuid.uuid4().hex
            params = {"image_id": source["id"], "rect": args.rect, "request_id": request_id}
            crop = client.tool("dm_crop", params)
            validate_receipt(crop, request_id, fixture["session"], "digitalmicrograph-native", args.expected_host_pid, status["host_thread"])
            require(crop.get("source_image_id") == source["id"] and crop["image_id"] != source["id"], "Crop object identity")
            require(crop.get("effective_rect") == args.rect and crop.get("requested_rect") == args.rect, "Crop coordinate identity")
            require(crop.get("operator") == "GMS::Image::GetSubSliceAsImage", "Crop must be a native copy")
            image = crop["image"]
            require(image["id"] == crop["image_id"] and image["shape"] == list(expected.shape)
                    and image["dtype"] == str(expected.dtype), "Crop shape/dtype")
            for d, offset in ((0, x0), (1, y0)):
                truth = source["calibration"][d]
                actual = image["calibration"][d]
                require(actual["dm_dimension"] == d and actual["unit"] == truth["unit"]
                        and actual["scale"] == truth["scale"]
                        and actual["calibrated_value_at_pixel_zero"] == truth["origin"] + offset * truth["scale"],
                        "Crop signed-scale physical origin")
            # Reusing the same immutable request returns the same object, not a
            # second crop. This is explicit client recovery, never an auto retry.
            repeated = client.tool("dm_crop", params)
            require(repeated == crop, "Duplicate crop request was executed again")
            mean_id = "crop-mean-" + uuid.uuid4().hex
            mean = client.tool("dm_native_mean", {"image_id": crop["image_id"], "request_id": mean_id})
            validate_receipt(mean, mean_id, fixture["session"], "digitalmicrograph-native", args.expected_host_pid, status["host_thread"])
            require(mean.get("operator") == "GMSImageProcessing::GetMean"
                    and mean.get("mean") == float(expected.mean(dtype=np.float64)), "Native crop mean mismatch")
            bad = client.rpc("tools/call", {"name": "dm_crop", "arguments": {"image_id": source["id"],
                "rect": [0, 0, source["shape"][1] + 1, 1], "request_id": "badcrop-" + uuid.uuid4().hex}})
            require("result" in bad and bad["result"].get("isError") is True, "Out-of-bounds crop falsely succeeded")
            summary.update(status="PASS", crop=crop, mean=mean,
                           expected_pixel_sha256=hashlib.sha256(expected.tobytes()).hexdigest(),
                           expected_mean=float(expected.mean(dtype=np.float64)), duplicate_object_reused=True,
                           invalid_roi_rejected=True)
        except Exception as error:
            summary["error"] = str(error)
            raise
        finally:
            client.close()
            (args.evidence_directory / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    print("PASS: actual MCP crop identity/calibration, duplicate recovery, native mean and invalid ROI")

if __name__ == "__main__":
    main()
