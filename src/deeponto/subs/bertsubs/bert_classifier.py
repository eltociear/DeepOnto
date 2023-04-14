# Copyright 2023 Jiaoyan Chen. All rights reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# @paper(
#     "Contextual Semantic Embeddings for Ontology Subsumption Prediction (World Wide Web Journal)",
# )

from typing import List

from datasets import Dataset
from sklearn.metrics import accuracy_score
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    EarlyStoppingCallback,
    Trainer,
    TrainingArguments,
)


class BERTSubsumptionClassifierTrainer:
    def __init__(
        self,
        bert_checkpoint: str,
        train_data: List,
        val_data: List,
        max_length: int = 128,
        early_stop: bool = False,
        early_stop_patience: int = 10,
    ):
        print(f"initialize BERT for Binary Classification from the Pretrained BERT model at: {bert_checkpoint} ...")

        # BERT
        self.model = AutoModelForSequenceClassification.from_pretrained(bert_checkpoint)
        self.tokenizer = AutoTokenizer.from_pretrained(bert_checkpoint)
        self.trainer = None

        self.max_length = max_length
        self.tra = self.load_dataset(train_data, max_length=self.max_length, count_token_size=True)
        self.val = self.load_dataset(val_data, max_length=self.max_length, count_token_size=True)
        print(f"text max length: {self.max_length}")
        print(f"data files loaded with sizes:")
        print(f"\t[# Train]: {len(self.tra)}, [# Val]: {len(self.val)}")

        # early stopping
        self.early_stop = early_stop
        self.early_stop_patience = early_stop_patience

    def add_special_tokens(self, tokens: List):
        r"""Add additional special tokens to the tokenizer.
        Args:
            tokens: additional tokens to add, e.g., ["<SUB>","<EOA>","<EOC>"]
        """
        special_tokens_dict = {"additional_special_tokens": tokens}
        self.tokenizer.add_special_tokens(special_tokens_dict)
        self.model.resize_token_embeddings(len(self.tokenizer))

    def train(self, train_args: TrainingArguments, do_fine_tune: bool = True):
        r"""initiate huggingface Trainer with input arguments and start training
        Args:
            train_args: huggingface trainer's arguments
            do_fine_tune: when it is set to false, we just load some (fine-tuned) checkpoint without further training
        """
        self.trainer = Trainer(
            model=self.model,
            args=train_args,
            train_dataset=self.tra,
            eval_dataset=self.val,
            compute_metrics=self.compute_metrics,
            tokenizer=self.tokenizer,
        )
        if self.early_stop:
            self.trainer.add_callback(EarlyStoppingCallback(early_stopping_patience=self.early_stop_patience))
        if do_fine_tune:
            self.trainer.train()

    @staticmethod
    def compute_metrics(pred):
        labels = pred.label_ids
        preds = pred.predictions.argmax(-1)
        acc = accuracy_score(labels, preds)
        return {"accuracy": acc}

    def load_dataset(self, data: List, max_length: int = 512, count_token_size: bool = False) -> Dataset:
        r"""load dataset from list
        Args:
            data: samples in List
            max_length: input sentence maximum length
            count_token_size: whether count the toke sizes of the data
        """
        # data_df = pd.DataFrame(data, columns=["sent1", "sent2", "labels"])
        # dataset = Dataset.from_pandas(data_df)

        def iterate():
            for sample in data:
                yield {"sent1": sample[0], "sent2": sample[1], "labels": sample[2]}

        dataset = Dataset.from_generator(iterate)

        if count_token_size:
            tokens = self.tokenizer(dataset["sent1"], dataset["sent2"])
            l_sum, num_128, num_256, num_512, l_max = 0, 0, 0, 0, 0
            for item in tokens["input_ids"]:
                l = len(item)
                l_sum += l
                if l <= 128:
                    num_128 += 1
                if l <= 256:
                    num_256 += 1
                if l <= 512:
                    num_512 += 1
                if l > l_max:
                    l_max = l
            print("average token size: %.2f" % (l_sum / len(tokens["input_ids"])))
            print("ratio of token size <= 128: %.3f" % (num_128 / len(tokens["input_ids"])))
            print("ratio of token size <= 256: %.3f" % (num_256 / len(tokens["input_ids"])))
            print("ratio of token size <= 512: %.3f" % (num_512 / len(tokens["input_ids"])))
            print("max token size: %d" % l_max)
        dataset = dataset.map(
            lambda examples: self.tokenizer(
                examples["sent1"], examples["sent2"], max_length=max_length, truncation=True
            ),
            batched=True,
            num_proc=1,
        )
        return dataset
