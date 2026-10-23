"""Strict real stdio MCP trial on NEW synthetic inputs; no DM start/stop.

Reads the private independent answers from create_trial_fixture.py. Protocol
receipts are checked separately from the one-shot host pixel/document oracles.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import uuid
from accept_mcp import StdioClient, ROOT, require, strict_json, validate_receipt, validate_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    parser.add_argument("--expected-host-pid", type=int, required=True)
    args = parser.parse_args()
    truth = strict_json(args.answers.read_text(encoding="utf-8-sig"))
    require(truth["kind"] == "synthetic-only" and truth["python_is_listener"] is False,
            "Explicit one-shot synthetic truth required")
    images = {entry["label"]: entry for entry in truth["images"]}
    require(set(images) == {"CAL", "RAW", "UINT16", "NONFINITE"}, "Wrong fixture labels")
    args.evidence_directory.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(DM_MCP_BACKEND="native", DM_NATIVE_SESSION=truth["session"], DM_MCP_TIMEOUT_MS="5000")
    report = {"status": "FAIL", "scope": "strict protocol client; no model viewing",
              "checks": [], "session": truth["session"]}
    host_thread = None
    def check_metadata(actual, expected, calibrated):
        normalized = dict(expected, calibration=[
            dict(axis, unit=axis["unit"] or None) for axis in expected["calibration"]])
        validate_image(actual, normalized)
        require(actual["data_type_code"] == 2
                and actual["calibration_complete"] is calibrated, "Wrong numeric input/calibration completeness")
        for axis in actual["calibration"]:
            expected_axis = next(item for item in expected["calibration"] if item["dm_axis"] == axis["dm_dimension"])
            require(axis["origin"] == expected_axis["raw_origin"] and axis["usable"] is calibrated
                    and axis["issue"] == (None if calibrated else "unknown_units"),
                    "Wrong raw origin or missing-unit issue")
    with (args.evidence_directory / "stdio-events.jsonl").open("x", encoding="utf-8") as trace:
        client = StdioClient([shutil.which("node") or "node", str(ROOT / "server.mjs")], env, trace)
        def call(name, arguments):
            saved_id = "trial-" + uuid.uuid4().hex
            output = client.tool(name, dict(arguments, request_id=saved_id))
            validate_receipt(output, saved_id, truth["session"], "digitalmicrograph-native",
                             args.expected_host_pid, host_thread)
            report["checks"].append({"tool": name, "output": output})
            return output
        def reject(name, arguments, expected_error, code="native_error", rpc=False):
            response = client.rpc("tools/call", {"name": name, "arguments": arguments})
            if rpc:
                require("result" not in response and response.get("error", {}).get("code") == -32602
                        and expected_error in response["error"].get("message", ""), "Wrong parameter error")
            else:
                require("error" not in response and response.get("result", {}).get("isError") is True,
                        "Native failure was reported in the wrong layer or as success")
                result = response["result"]
                require(len(result["content"]) == 1 and result["content"][0]["type"] == "text",
                        "Wrong native failure content")
                output = strict_json(result["content"][0]["text"])
                receipt = output["native_receipt"]
                require(receipt["state"] == "failed" and receipt["session"] == truth["session"]
                        and receipt["id"] == arguments["request_id"]
                        and receipt["request_id"] == arguments["request_id"]
                        and receipt["host_pid"] == args.expected_host_pid
                        and receipt["exec_tid"] == (host_thread if code == "native_error" else 0)
                        and receipt["code"] == code and receipt["error"] == expected_error
                        and output["error"] == expected_error,
                        "Wrong native error, unknown/timeout/disconnect must not count as rejection")
            report["checks"].append({"tool": name, "expected_error": response})
            return response
        try:
            require("error" not in client.rpc("initialize", {"protocolVersion": "2024-11-05",
                "capabilities": {}, "clientInfo": {"name": "native-usability-acceptance", "version": "1"}}),
                "Initialize failed")
            client.notify("notifications/initialized")
            catalog = client.rpc("tools/list", {})["result"]["tools"]
            crop_schema = next(tool["inputSchema"] for tool in catalog if tool["name"] == "dm_crop")
            require("request_id" in crop_schema["required"], "Crop recovery ID is not required")
            show_schema = next(tool["inputSchema"] for tool in catalog if tool["name"] == "dm_native_show")
            require(set(show_schema["required"]) == {"image_id", "request_id"}, "Show recovery ID not required")
            status = call("dm_status", {})
            require(status["ready"] is True and status["binary_gate"] is True, "Host not ready")
            host_thread = status["host_thread"]
            datasets = call("dm_datasets", {})["datasets"]
            for label in ("CAL", "RAW"):
                source = images[label]
                info = next(item for item in datasets if item["id"] == source["id"])
                check_metadata(info, source, label == "CAL")
                output = call("dm_native_mean", {"image_id": source["id"]})
                require(output["image_id"] == source["id"] and output["image"]["id"] == source["id"]
                        and output["operator"] == "GMSImageProcessing::GetMean"
                        and output["mean"] == source["mean"], "Raw mean identity/operator/truth mismatch")
                require(output["intensity_calibration_applied"] is False
                        and output["intensity_semantics"] == "raw pixel intensity", "False intensity semantics")
                check_metadata(output["image"], source, label == "CAL")
            for label, error in (("UINT16", "native_mean_requires_float32_2d"),
                                 ("NONFINITE", "native_mean_nonfinite_result")):
                reject("dm_native_mean", {"image_id": images[label]["id"],
                       "request_id": "bad-" + uuid.uuid4().hex}, error)
            reject("dm_native_mean", {"image_id": 0xffffffff, "request_id": "missing-" + uuid.uuid4().hex},
                   "image_not_found")
            source = images["CAL"]
            reject("dm_crop", {"image_id": source["id"], "rect": truth["crop_rect"]},
                   "request_id", rpc=True)
            reject("dm_crop", {"image_id": images["RAW"]["id"], "rect": truth["crop_rect"],
                               "request_id": "rawcrop-" + uuid.uuid4().hex}, "unknown_image_units")
            crop_id = "crop-" + uuid.uuid4().hex
            params = {"image_id": source["id"], "rect": truth["crop_rect"], "request_id": crop_id}
            # Persist the recovery ID in trace before dispatch. Only QUERY is
            # used to recover the existing result, never a replacement crop.
            crop = client.tool("dm_crop", params)
            validate_receipt(crop, crop_id, truth["session"], "digitalmicrograph-native",
                             args.expected_host_pid, status["host_thread"])
            recovered = client.tool("dm_native_result", {"request_id": crop_id})
            require(recovered == crop, "Query recovered a different crop or receipt")
            duplicate = client.tool("dm_crop", params)
            require(duplicate == crop, "Explicit duplicate created another result")
            reject("dm_crop", dict(params, rect=[0, 0, 1, 1]),
                   "id is already bound to different operation parameters", code="id_conflict")
            crop_mean = call("dm_native_mean", {"image_id": crop["image_id"]})
            require(crop_mean["image_id"] == crop["image_id"]
                    and crop_mean["image"]["id"] == crop["image_id"]
                    and crop_mean["operator"] == "GMSImageProcessing::GetMean"
                    and crop_mean["mean"] == source["crop_mean"]
                    and crop_mean["intensity_calibration_applied"] is False
                    and crop_mean["intensity_semantics"] == "raw pixel intensity", "Crop raw mean identity/operator/truth mismatch")
            x0, y0, x1, y1 = truth["crop_rect"]
            expected_crop = dict(source, id=crop["image_id"], name=crop["image"]["name"],
                shape=[y1-y0, x1-x0], calibration=[
                    dict(axis, origin=axis["origin"] + (x0 if axis["dm_axis"] == 0 else y0) * axis["scale"],
                         raw_origin=axis["raw_origin"] - (x0 if axis["dm_axis"] == 0 else y0))
                    for axis in source["calibration"]])
            check_metadata(crop["image"], expected_crop, True)
            check_metadata(crop_mean["image"], expected_crop, True)
            reject("dm_native_show", {"image_id": crop["image_id"]}, "request_id", rpc=True)
            delivery_id = "show-" + uuid.uuid4().hex
            show_params = {"image_id": crop["image_id"], "request_id": delivery_id}
            delivery = client.tool("dm_native_show", show_params)
            validate_receipt(delivery, delivery_id, truth["session"], "digitalmicrograph-native",
                             args.expected_host_pid, host_thread)
            require(delivery["image_id"] == crop["image_id"]
                    and delivery["delivery"] == "visible_dm_document"
                    and delivery["document_visible"] is True
                    and delivery["file_saved"] is False
                    and delivery["model_visual_verification"] is False, "Wrong delivery claim")
            require(client.tool("dm_native_result", {"request_id": delivery_id}) == delivery,
                    "Show query recovered a different result")
            require(client.tool("dm_native_show", show_params) == delivery,
                    "Duplicate show did not preserve original result")
            # A distinct explicit request must reuse the image's associated
            # document too; document count is checked independently in DM.
            repeated_show = call("dm_native_show", {"image_id": crop["image_id"]})
            require(repeated_show["image_id"] == crop["image_id"], "Show selected the wrong image")
            report.update(status="PASS", crop=crop, crop_mean=crop_mean,
                          delivery=delivery, repeated_show=repeated_show,
                          same_session_query_recovery=True, duplicate_object_reused=True,
                          missing_id_rejected=True)
        except Exception as error:
            report["error"] = str(error)
            raise
        finally:
            client.close()
            (args.evidence_directory / "summary.json").write_text(
                json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print("PASS: calibrated/unlabelled native means, required recovery ID, crop/query and safe errors")


if __name__ == "__main__":
    main()
