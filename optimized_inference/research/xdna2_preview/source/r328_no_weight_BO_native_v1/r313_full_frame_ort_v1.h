#pragma once

#include "r209_pair_ort_v1.h"
#include "r313_host_reply_v1.h"

namespace r313 {

template<class Channel>
struct FullFrameKernel {
  Channel* channel;

  FullFrameKernel(Channel* owner, const OrtKernelInfo* raw) : channel(owner) {
    const Ort::ConstKernelInfo info(raw);
    r101::require(
        info.GetAttribute<std::int64_t>("model") == channel->model &&
        info.GetAttribute<std::string>("track") == "performance" &&
        info.GetAttributes<std::int64_t>("branch_rows") == std::vector<std::int64_t>{40, 48} &&
        info.GetAttribute<std::int64_t>("hidden_size") == 256 &&
        info.GetAttributes<std::int64_t>("cell_order") == std::vector<std::int64_t>{0, 1, 2, 3, 4} &&
        info.GetAttributes<std::int64_t>("archived_cells") == std::vector<std::int64_t>{0, 1, 3} &&
        info.GetAttributes<std::int64_t>("CPU_visible_hidden_cells") == std::vector<std::int64_t>{2, 4} &&
        info.GetAttributes<std::int64_t>("side_shape") == std::vector<std::int64_t>{1, 16, 1, 32} &&
        info.GetAttribute<std::string>("encoder_precision") == "bf16-rne-fp32-accumulate" &&
        info.GetAttribute<std::string>("recurrent_profile") ==
            "u8W8-exact-rowquant-IEEE-dequant-H256-poly6f3p2-original-update-v1",
        "Full-frame operator attributes differ");
  }

  OrtStatusPtr ComputeV2(OrtKernelContext* raw) noexcept {
    try {
      Ort::KernelContext context(raw);
      Inputs input{};
      Outputs output{};
      r101::require(context.GetInputCount() == input.size() && context.GetOutputCount() == output.size(),
                    "Full-frame operator arity differs");
      for (std::size_t lane = 0; lane < r293::branch_rows.size(); ++lane) {
        const std::array<std::int64_t, 4> wanted{1, 64, 1, static_cast<std::int64_t>(r293::branch_rows[lane])};
        const auto value = context.GetInput(lane);
        const auto shape = value.GetTensorTypeAndShapeInfo();
        std::array<std::int64_t, 4> dims{};
        r101::require(shape.GetElementType() == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT &&
                      shape.GetDimensionsCount() == dims.size(), "Full-frame DPRNN dtype or rank");
        Ort::ThrowOnError(Ort::GetApi().GetDimensions(shape, dims.data(), dims.size()));
        r101::require(dims == wanted, "Full-frame DPRNN shape differs");
        input[lane] = value.GetTensorData<float>();
      }
      constexpr auto hidden = r209::hidden_shape;
      constexpr std::array<std::int64_t, 4> side{1, 16, 1, 32};
      for (std::size_t i = 0; i < visible_cells.size(); ++i) {
        output[i] = context.GetOutput(i, hidden.data(), hidden.size()).GetTensorMutableData<float>();
      }
      output.back() = context.GetOutput(visible_cells.size(), side.data(), side.size()).GetTensorMutableData<float>();
      channel->full_frame(input, output);
      return nullptr;
    } catch (const std::exception& error) {
      return Ort::GetApi().CreateStatus(ORT_FAIL, error.what());
    } catch (...) {
      return Ort::GetApi().CreateStatus(ORT_FAIL, "Full-frame callback failed");
    }
  }
};

template<class Channel>
struct FullFrameOp : Ort::CustomOpBase<FullFrameOp<Channel>, FullFrameKernel<Channel>, true> {
  Channel* channel;

  explicit FullFrameOp(Channel* owner) : channel(owner) {}
  const char* GetName() const { return "NpuFullRecurrentPcmFrame256"; }
  const char* GetExecutionProviderType() const { return "CPUExecutionProvider"; }
  std::size_t GetInputTypeCount() const { return Inputs{}.size(); }
  std::size_t GetOutputTypeCount() const { return Outputs{}.size(); }
  ONNXTensorElementDataType GetInputType(std::size_t) const { return ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT; }
  ONNXTensorElementDataType GetOutputType(std::size_t) const { return ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT; }

  OrtStatusPtr CreateKernelV2(const OrtApi& api, const OrtKernelInfo* raw, void** kernel) const noexcept {
    try {
      *kernel = new FullFrameKernel<Channel>(channel, raw);
      return nullptr;
    } catch (const std::exception& error) {
      return api.CreateStatus(ORT_FAIL, error.what());
    } catch (...) {
      return api.CreateStatus(ORT_FAIL, "Full-frame operator initialization failed");
    }
  }
};

}  // namespace r313
